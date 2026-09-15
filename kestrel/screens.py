"""Public, read-only projections of world state for planners and replays."""
from copy import deepcopy

from . import calendar as cal
from .finance import PNL_GROUPS
from .network import COMPONENTS, CUSTOMERS, DCS, NODES, PRODUCTS, SUPPLIERS
from .records import CLOSED


HIDDEN = {"lane", "lane_age", "rate_regime", "supplier_health", "alloc", "alloc_age",
          "port_q", "strike_until", "spot", "defects_true", "health"}

# Public business-document fields. Dates that encode sampled future outcomes are
# added by _record_data only after the corresponding event becomes observable.
PUBLIC_DATA = {
    "po": ("supplier", "component", "qty", "confirmed_qty", "requested_day", "promised_day",
           "incoterm", "unit_price", "deposit_paid", "balance_paid", "expedited", "asn_id",
           "receipt_id", "lot_id", "invoice_id", "shipped_qty"),
    "asn": ("po_id", "supplier", "component", "qty"),
    "receipt": ("po_id", "supplier", "component", "qty"),
    "lot": ("po_id", "supplier", "component", "qty"),
    "invoice_in": ("po_id", "supplier", "amount", "expected", "due_day", "dispute_day"),
    "booking": ("mode", "route", "lines", "rate_type", "containers", "cutoff_day", "freight",
                "surcharges", "demurrage_paid"),
    "contract": ("price", "min_per_month", "used_this_month", "start_day", "end_day"),
    "work_order": ("sku", "qty", "produced", "started_day"),
    "transfer": ("src", "dst", "mode", "lines", "pallets", "cost"),
    "order": ("customer", "sku", "qty", "allocated_qty", "shipped_qty", "requested_day",
              "value", "invoice_id"),
    "invoice_out": ("order_id", "amount", "due_day"),
    "chargeback": ("order_id", "amount", "due_day"),
    "credit_note": ("po_id", "lot_id", "supplier", "component", "qty", "order_id", "amount"),
    "ret": ("order_id", "customer", "sku", "qty", "unit_price", "restocked_qty", "written_off_qty"),
    "qualification": ("supplier", "done_day"),
    "audit": ("supplier",),
}


def _record_data(rec):
    data = {k: deepcopy(rec.data[k]) for k in PUBLIC_DATA.get(rec.type, ()) if k in rec.data}
    if rec.type == "po" and rec.state in {"shipped", "received", "inspected", "invoiced", "matched", "paid", "short_closed"}:
        data["actual_ship_day"] = rec.data.get("ship_day")
        data["carrier_estimated_arrival_day"] = rec.data.get("arrival_day")
    elif rec.type == "booking":
        if rec.state in {"loaded", "at_sea", "arrived", "customs", "cleared", "delivered"}:
            data["actual_load_day"] = rec.data.get("load_day")
            data["carrier_estimated_arrival_day"] = rec.data.get("eta_day")
        if rec.state in {"arrived", "customs", "cleared", "delivered"}:
            data["actual_arrival_day"] = rec.data.get("arrival_day")
            data["free_until"] = rec.data.get("free_until")
        if rec.state in {"customs", "cleared", "delivered"}:
            data["customs_estimated_clearance_day"] = rec.data.get("cleared_day")
    elif rec.type == "transfer":
        data["carrier_estimated_arrival_day"] = rec.data.get("eta_day")
    elif rec.type == "order":
        if rec.state in {"shipped", "delivered"}:
            data["actual_ship_day"] = rec.data.get("ship_day")
            data["carrier_estimated_delivery_day"] = rec.data.get("deliver_day")
        if rec.state == "delivered":
            data.update(actual_delivery_day=rec.data.get("deliver_day"), late=rec.data.get("late"), short=rec.data.get("short"))
    elif rec.type == "ret":
        data["carrier_estimated_arrival_day"] = rec.data.get("arrive_day")
    elif rec.type == "audit" and rec.state == "done":
        data["health"] = rec.data.get("health")
    return data


def record_view(rec):
    return {"id": rec.id, "type": rec.type, "state": rec.state, "created_day": rec.created_day,
            "history": deepcopy(rec.history), "data": _record_data(rec)}


def _inventory(world, forecast):
    out = {}
    for node in NODES:
        out[node] = {}
        items = COMPONENTS + tuple(PRODUCTS) if node == "PLANT" else tuple(PRODUCTS)
        for item in items:
            in_transit = 0
            on_order = 0
            if node == "PLANT" and item in COMPONENTS:
                pos = [r for r in world.records.open("po") if r.data["component"] == item]
                in_transit = sum(r.data.get("shipped_qty") or 0 for r in pos if r.state == "shipped")
                on_order = sum((r.data.get("confirmed_qty") or r.data["qty"]) for r in pos if r.state in {"draft", "confirmed", "in_production"})
            elif item in PRODUCTS:
                for r in world.records.open("booking"):
                    if node == "DC-NL": in_transit += r.data.get("lines", {}).get(item, 0)
                for r in world.records.open("transfer"):
                    if r.data.get("dst") == node: in_transit += r.data.get("lines", {}).get(item, 0)
                in_transit += sum(qty for sku, qty in world.dc_inbound_queue.get(node, ()) if sku == item)
            share = (sum(c.share for c in CUSTOMERS.values() if c.dc == node)
                     if node in DCS else 1.0)
            demand = forecast[item][0] * share / 5 if item in PRODUCTS else 0
            out[node][item] = {"on_hand": world.stock[node].get(item, 0),
                               "allocated": world.allocated.get(node, {}).get(item, 0),
                               "in_transit_to": in_transit, "on_order": on_order,
                               "days_of_cover": round(world.stock[node].get(item, 0) / demand, 1) if demand else None}
    return out


def _finance(world):
    receivables = sum(r.data["amount"] for r in world.records.open("invoice_out"))
    payables = sum(r.data["amount"] for r in world.records.open("invoice_in") if r.state != "paid")
    start = max(0, world.day - 89)
    revenue = world.ledger.total("revenue", start, world.day)
    cogs = -sum(world.ledger.total(c, start, world.day) for c in PNL_GROUPS["cogs"])
    wc = world.ledger.working_capital(world.day, receivables, payables, world.inventory_value(), revenue, cogs)
    return {"cash": round(world.ledger.cash, 2), "receivables": round(receivables, 2),
            "payables": round(payables, 2), "pnl": world.ledger.pnl(world.day), "working_capital": wc}


def build(world):
    forecast = world.demand.forecast(world.day)
    records = {kind: [record_view(r) for r in world.records.open(kind)] for kind in CLOSED}
    records["closed_counts"] = {kind: len(world.records.all(kind)) - len(world.records.open(kind)) for kind in CLOSED}
    suppliers = {}
    for sid, supplier in SUPPLIERS.items():
        audits = [r for r in world.records.all("audit") if r.state == "done" and r.data["supplier"] == sid]
        suppliers[sid] = {"components": list(supplier.components), "qualified": world.qualified[sid],
                          "moq": deepcopy(supplier.moq), "price_breaks": deepcopy(supplier.breaks),
                          "quoted_lead_days": {c: world.cond.quoted_lead(sid, c) for c in supplier.components},
                          "scorecard": deepcopy(world.scorecards.get(sid)),
                          "audit": ({"id": audits[-1].id, "completed_day": audits[-1].history[-1][0],
                                     "health": audits[-1].data["health"]} if audits else None)}
    customers = {}
    for cid, customer in CUSTOMERS.items():
        orders = [r for r in world.records.all("order") if r.data["customer"] == cid]
        delivered = [r for r in orders if r.state == "delivered"]
        good = sum(not r.data["late"] and not r.data["short"] for r in delivered)
        chargebacks = [r for r in world.records.all("chargeback") if world.records.get(r.data["order_id"]).data["customer"] == cid]
        customers[cid] = {"dc": customer.dc, "open_orders": [record_view(r) for r in orders if r.state not in CLOSED["order"]],
                          "otif_to_date": good / len(delivered) if delivered else 0.0,
                          "chargebacks_to_date": round(sum(r.data["amount"] for r in chargebacks), 2),
                          "promos": deepcopy([p for p in world.demand.announced_promos(world.day) if p["customer"] == cid])}
    screen = {
        "calendar": {"today": world.day, "date": cal.to_date(world.day).isoformat(),
                     "weekday": cal.to_date(world.day).strftime("%A"),
                     "events": [deepcopy(e) for e in cal.EVENTS if e["end_day"] >= world.day and e["start_day"] <= world.day + 60],
                     "promos_announced": deepcopy(world.demand.announced_promos(world.day)),
                     "blank_sailings": deepcopy(world.blank_sailings)},
        "inventory": _inventory(world, forecast), "records": records,
        "exceptions": deepcopy(world.exceptions), "news": deepcopy(world.news),
        "market": {"spot_rate_index": round(world.cond.spot_rate() / 10) * 10,
                   "air_rate_per_kg": 6.0, "contract_rate": world.contract.data["price"] if world.contract and world.contract.state == "active" else None,
                   "pss_in_season": cal.pss_in_season(world.day),
                   "booking_tightness": "tight" if cal.freight_tight(world.day) or world.cond.spot_rate() >= 5000 else "normal"},
        "suppliers": suppliers, "customers": customers, "finance": _finance(world), "forecast": forecast,
    }
    _assert_boundary(screen)
    return screen


def _assert_boundary(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in HIDDEN and not (key == "health" and "audit" in path and child is not None):
                raise AssertionError(f"hidden screen key at {path + (key,)}")
            _assert_boundary(child, path + (key,))
    elif isinstance(value, (list, tuple)):
        for child in value: _assert_boundary(child, path)
