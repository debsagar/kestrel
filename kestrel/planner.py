"""Small deterministic replenishment policy driven solely by player-visible screens.

Regional safety includes a 14-day ordering-cycle buffer. Full-calendar trials
showed the statistical lead-time term alone could not cover weekly customer
order batches, so the policy buffer is tuned here rather than in world physics.
"""
import math

from . import calendar as cal
from .network import COMPONENTS, CUSTOMERS, PRODUCTS, PRIMARY_SUPPLIER


Z = {"A": 2.33, "B": 1.65}
SAFETY_DAYS = {sku: 14 + Z[p.abc] * 0.35 for sku, p in PRODUCTS.items()}
REGIONAL_LEAD = {"DC-DE": 1, "DC-PL": 3}
PLANT_CAPACITY = 4000


def _up(value, multiple):
    return math.ceil(value / multiple) * multiple


def _daily(screen, sku):
    return screen["forecast"][sku][0] / 5


def _open(screen, kind):
    return screen["records"].get(kind, [])


def _exception_actions(screen):
    actions = []
    invoices = {r["id"]: r for r in _open(screen, "invoice_in")
                if r["state"] in {"open", "blocked"}}
    lots = {r["id"]: r for r in _open(screen, "lot")}
    for item in screen["exceptions"]:
        ref = item.get("ref")
        if item.get("kind") == "invoice" and ref in invoices:
            data = invoices[ref]["data"]
            kind = "accept_invoice" if data["amount"] <= data["expected"] * 1.01 else "dispute_invoice"
            actions.append({"type": kind, "invoice_id": ref})
        elif item.get("kind") == "quality" and ref in lots:
            pass  # sorting is automatic

    supplier_problem = any(item.get("kind") == "supplier" for item in screen["exceptions"])
    pending = {r["data"]["supplier"] for r in _open(screen, "qualification")}
    if supplier_problem and not screen["suppliers"]["S-BRK"]["qualified"] and "S-BRK" not in pending:
        actions.append({"type": "qualify_supplier", "supplier": "S-BRK"})

    today = screen["calendar"]["today"]
    low_components = {c for c in COMPONENTS if screen["inventory"]["PLANT"][c]["on_hand"] == 0}
    for po in _open(screen, "po"):
        data = po["data"]
        if (po["state"] in {"confirmed", "in_production"} and not data.get("expedited")
                and data.get("promised_day") is not None and data["promised_day"] < today
                and data["component"] in low_components):
            actions.append({"type": "expedite_po", "po_id": po["id"]})
    return actions


def _contract_action(screen):
    today = screen["calendar"]["today"]
    if cal.contract_window(today) and cal.to_date(today).day == 1 and screen["market"]["contract_rate"] is None:
        volume = sum(_daily(screen, sku) * 30 / product.per_container
                     for sku, product in PRODUCTS.items())
        return [{"type": "sign_freight_contract", "containers_per_month": max(4, math.ceil(volume))}]
    return []


def _transfer_actions(screen, available):
    actions = []
    for dc, lead in REGIONAL_LEAD.items():
        share = sum(c.share for c in CUSTOMERS.values() if c.dc == dc)
        for sku, product in PRODUCTS.items():
            daily = _daily(screen, sku) * share
            position = screen["inventory"][dc][sku]
            target = daily * (lead + 14 + (SAFETY_DAYS[sku] - 14) * math.sqrt(lead))
            deficit = math.ceil(target - position["on_hand"] - position["in_transit_to"])
            if deficit <= 0 or available[sku] <= 0:
                continue
            qty = min(_up(deficit, product.per_pallet), available[sku])
            qty -= qty % product.per_pallet
            if qty <= 0:
                continue
            cover = position["on_hand"] / daily if daily else float("inf")
            mode = "air" if cover < lead and product.abc == "A" else "rail"
            actions.append({"type": "create_transfer", "src": "DC-NL", "dst": dc,
                            "mode": mode, "lines": {sku: qty}})
            available[sku] -= qty
    return actions


def _booking_actions(screen, plant_available):
    actions = []
    contract = screen["market"]["contract_rate"] is not None
    nl_available = {sku: screen["inventory"]["DC-NL"][sku]["on_hand"] for sku in PRODUCTS}
    for sku, product in PRODUCTS.items():
        daily = _daily(screen, sku)
        total = (plant_available[sku] + nl_available[sku]
                 + screen["inventory"]["DC-NL"][sku]["in_transit_to"])
        deficit = math.ceil(daily * 40 - total)
        regional_short = any(
            screen["inventory"][dc][sku]["days_of_cover"] is not None
            and screen["inventory"][dc][sku]["days_of_cover"] < 7
            for dc in REGIONAL_LEAD
        )
        if regional_short and nl_available[sku] < daily * 7 and plant_available[sku] > 0:
            qty = min(max(1, deficit), plant_available[sku])
            actions.append({"type": "book_container", "mode": "air", "route": None,
                            "rate_type": "spot", "lines": {sku: qty}})
            plant_available[sku] -= qty
        elif deficit >= product.per_container and plant_available[sku] >= product.per_container:
            qty = min(_up(deficit, product.per_container),
                      plant_available[sku] // product.per_container * product.per_container)
            if qty:
                actions.append({"type": "book_container", "mode": "ocean", "route": "suez",
                                "rate_type": "contract" if contract else "spot", "lines": {sku: qty}})
                plant_available[sku] -= qty
    return actions


def _work_order_actions(screen, component_available, plant_available):
    actions = []
    remaining_capacity = PLANT_CAPACITY
    open_skus = {r["data"]["sku"] for r in _open(screen, "work_order")}
    for sku, product in PRODUCTS.items():
        if sku in open_skus or remaining_capacity < product.eq_units:
            continue
        deficit = math.ceil(_daily(screen, sku) * 10 - plant_available[sku])
        qty = min(deficit, remaining_capacity // product.eq_units)
        if qty <= 0:
            continue
        qty = min(qty, *(component_available[c] // per for c, per in product.bom.items()))
        if qty <= 0:
            continue
        actions.append({"type": "release_work_order", "sku": sku, "qty": qty})
        remaining_capacity -= qty * product.eq_units
        for component, per in product.bom.items():
            component_available[component] -= qty * per
    return actions


def _po_actions(screen):
    actions = []
    for component in COMPONENTS:
        primary = PRIMARY_SUPPLIER[component]
        supplier = primary
        primary_view = screen["suppliers"][primary]
        lead = primary_view["quoted_lead_days"][component]
        if lead > 75 and screen["suppliers"]["S-BRK"]["qualified"] and component == "SOC":
            supplier = "S-BRK"
            lead = screen["suppliers"][supplier]["quoted_lead_days"][component]
        required = sum(_daily(screen, sku) * product.bom.get(component, 0)
                       for sku, product in PRODUCTS.items()) * (lead + 14)
        position = screen["inventory"]["PLANT"][component]
        deficit = math.ceil(required - position["on_hand"] - position["on_order"] - position["in_transit_to"])
        if deficit <= 0:
            continue
        view = screen["suppliers"][supplier]
        moq = view["moq"][component]
        qty = _up(deficit, moq)
        for breakpoint, _price in view["price_breaks"][component]:
            if qty < breakpoint <= qty * 1.2:
                qty = breakpoint
                break
        actions.append({"type": "create_po", "supplier": supplier, "component": component,
                        "qty": qty, "requested_day": screen["calendar"]["today"] + lead})
    return actions


def plan_day(world):
    """Return today's ordered action batch without mutating the world."""
    screen = world.screens()
    nl_available = {sku: screen["inventory"]["DC-NL"][sku]["on_hand"] for sku in PRODUCTS}
    plant_available = {sku: screen["inventory"]["PLANT"][sku]["on_hand"] for sku in PRODUCTS}
    components = {c: screen["inventory"]["PLANT"][c]["on_hand"] for c in COMPONENTS}
    actions = _exception_actions(screen) + _contract_action(screen)
    actions += _transfer_actions(screen, nl_available)
    actions += _booking_actions(screen, plant_available)
    actions += _work_order_actions(screen, components, plant_available)
    actions += _po_actions(screen)
    return actions


def note(world):
    screen = world.screens()
    low = [sku for sku in PRODUCTS if any(screen["inventory"][dc][sku]["days_of_cover"] < 7
                                           for dc in REGIONAL_LEAD)]
    return "Protect regional service and replenish the network" + (f"; urgent: {', '.join(low)}" if low else ".")


def run(world, days):
    """Run up to ``days`` and retain submitted actions and their real results."""
    reports = []
    for _ in range(days):
        if world.done:
            break
        actions = plan_day(world)
        results = [world.apply(action) for action in actions]
        report = world.end_day()
        report.update(actions=actions, results=results)
        reports.append(report)
    return reports
