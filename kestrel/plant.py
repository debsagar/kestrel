"""The assembly plant: work orders, daily capacity, changeover, and yield (SPEC S5.3).

A work order is released with components consumed up front (reserved), then advance()
turns eq-capacity into finished goods each plant working day, subject to Chinese-New-Year /
Golden-Week capacity factors and a changeover penalty when the SKU on the line changes.
"""
from . import calendar as cal
from .network import PRODUCTS, component_cost
from .records import transition

CAPACITY, CHANGEOVER, YIELD = 4000, 400, 0.98


def _defect_rate(world, sku) -> float:
    """BOM-quantity-weighted mean of world.component_dppm[c] over the SKU's components,
    fixed at release (controller ruling 1)."""
    bom = PRODUCTS[sku].bom
    total = sum(bom.values())
    return sum(q * world.component_dppm[c] for c, q in bom.items()) / total


# -- planner actions ----------------------------------------------------------

def release_work_order(world, a):
    sku = a.get("sku")
    if sku not in PRODUCTS: raise ValueError(f"unknown sku {sku!r}")
    if "qty" not in a: raise ValueError("qty is required")
    qty = a["qty"]
    if type(qty) is not int or qty <= 0:
        raise ValueError(f"qty must be a positive integer, got {qty!r}")
    bom = PRODUCTS[sku].bom
    for c, per_unit in bom.items():
        need, have = per_unit * qty, world.stock["PLANT"].get(c, 0)
        if need > have: raise ValueError(f"PLANT has {have} {c}, need {need} for {qty} {sku}")
    defect_rate = _defect_rate(world, sku)
    for c, per_unit in bom.items():
        world.take_stock("PLANT", c, per_unit * qty)
        world.flows["consumed_components"] += per_unit * qty
    day = world.day
    rec = world.records.new("work_order", day, "planned", sku=sku, qty=qty, produced=0, started_day=day, defect_rate=defect_rate)
    transition(rec, "released", day, "released")
    world.log(f"work order {rec.id}: {qty} {sku} released, defect_rate {defect_rate:.1f} dppm")
    return {"id": rec.id}


def cancel_work_order(world, a):
    wo_id = a.get("work_order_id")
    if not wo_id: raise ValueError("work_order_id is required")
    try: wo = world.records.get(wo_id)
    except KeyError: raise KeyError(f"no such work order {wo_id!r}")
    if wo.state not in ("planned", "released"):
        raise ValueError(f"work order {wo.id} cannot be cancelled from state {wo.state!r}")
    remaining = wo.data["qty"] - wo.data["produced"]
    for c, per_unit in PRODUCTS[wo.data["sku"]].bom.items():
        world.add_stock("PLANT", c, per_unit * remaining)
        world.flows["consumed_components"] -= per_unit * remaining
    transition(wo, "cancelled", world.day, "cancelled by planner")
    return {"id": wo.id}


ACTIONS = {"release_work_order": release_work_order, "cancel_work_order": cancel_work_order}


# -- daily lifecycle ------------------------------------------------------------

def advance(world):
    day = world.day
    if not cal.is_working("plant", day): return
    remaining = int(CAPACITY * cal.china_capacity_factor(day))
    for wo in world.records.open("work_order"):
        if remaining <= 0: continue
        sku = wo.data["sku"]
        eq = PRODUCTS[sku].eq_units
        if sku != world.last_sku and world.last_sku is not None:
            remaining -= CHANGEOVER
        if remaining <= 0: continue
        units_today = min(remaining // eq, wo.data["qty"] - wo.data["produced"])
        if units_today <= 0: continue
        if wo.state == "released": transition(wo, "running", day, "production started")
        wo.data["produced"] += units_today
        finished = round(units_today * YIELD * (1 - wo.data["defect_rate"] / 1e6))
        world.add_stock("PLANT", sku, finished)
        world.flows["produced"] += finished
        scrap = units_today - finished
        if scrap:
            world.ledger.post(day, "writeoffs", -((component_cost(sku) + PRODUCTS[sku].assembly_cost) * scrap), wo.id)
        world.last_sku = sku
        remaining -= units_today * eq
        world.log(f"work order {wo.id}: produced {units_today} {sku} ({finished} finished goods)")
        if wo.data["produced"] == wo.data["qty"]:
            transition(wo, "complete", day, "production complete")


def seed_opening(world): pass
