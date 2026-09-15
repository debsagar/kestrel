"""Inter-DC transfers and DC receiving: rail/truck/air transfers between DCs, and draining
logistics' dc_inbound_queue into DC stock on DC working days, capacity-limited (SPEC S5.4).
"""
from . import calendar as cal
from . import network
from .network import DCS, LEGS, PRODUCTS
from .records import transition


def create_transfer(world, a):
    src, dst, mode = a.get("src"), a.get("dst"), a.get("mode")
    key = (src, dst, mode)
    if key not in LEGS:
        raise ValueError(f"no such leg {src!r} -> {dst!r} via {mode!r}")
    lines_in = a.get("lines")
    if not isinstance(lines_in, dict) or not lines_in: raise ValueError("lines must be a non-empty mapping")
    lines = {}
    for sku, qty in lines_in.items():
        if sku not in PRODUCTS: raise ValueError(f"unknown sku {sku!r}")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"quantity for {sku!r} must be a positive int, got {qty!r}")
        lines[sku] = qty
    for sku, qty in lines.items():
        have = world.stock[src].get(sku, 0) - world.allocated.get(src, {}).get(sku, 0)
        if qty > have: raise ValueError(f"{src} has {have} {sku}, need {qty}")
    for sku, qty in lines.items():
        world.take_stock(src, sku, qty)
    pallets = sum(network.pallets(sku, qty) for sku, qty in lines.items())
    leg = LEGS[key]
    day = world.day
    if leg["sd"] > 0:
        eta_day = day + max(1, round(leg["mean"] + world.rng_ops.gauss(0, leg["sd"])))
    else:
        eta_day = day + leg["mean"]
    cost = pallets * leg["cost"]
    rec = world.records.new("transfer", day, "created", src=src, dst=dst, mode=mode, lines=lines,
                             pallets=pallets, eta_day=eta_day, cost=cost)
    transition(rec, "in_transit", day, "in transit")
    world.ledger.post(day, "inter_dc", -cost, rec.id)
    world.log(f"transfer {rec.id}: {src} -> {dst} via {mode}, {lines}, {pallets} pallets, cost {cost:.2f}")
    return {"id": rec.id}


ACTIONS = {"create_transfer": create_transfer}


# -- daily lifecycle ------------------------------------------------------------

def _deliver(world):
    day = world.day
    for tr in world.records.open("transfer"):
        if tr.state == "in_transit" and tr.data["eta_day"] <= day:
            transition(tr, "delivered", day, "delivered to DC inbound queue")
            for sku, qty in tr.data["lines"].items():
                world.dc_inbound_queue[tr.data["dst"]].append((sku, qty))


def _receive(world):
    day = world.day
    if not cal.is_working("dc", day): return
    for dc in DCS:
        queue = world.dc_inbound_queue[dc]
        if not queue: continue
        total_pallets = sum(network.pallets(sku, qty) for sku, qty in queue)
        capacity = world.dc_inbound_capacity[dc]
        if total_pallets > 3 * capacity:
            world.exception("dc", dc, f"{dc} inbound queue holds {total_pallets} pallets, over 3x capacity {capacity}")
        while queue and capacity > 0:
            sku, qty = queue[0]
            need = network.pallets(sku, qty)
            if need <= capacity:
                world.add_stock(dc, sku, qty)
                queue.pop(0)
                capacity -= need
            else:
                move = capacity * PRODUCTS[sku].per_pallet
                world.add_stock(dc, sku, move)
                queue[0] = (sku, qty - move)
                capacity = 0


def advance(world):
    _deliver(world)
    _receive(world)


def seed_opening(world): pass
