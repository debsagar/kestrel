"""Independent consistency checks derived from physical records and balances."""
from .finance import CASH
from .network import COMPONENTS, PRODUCTS, component_cost
from .records import LEGAL
from .screens import HIDDEN


def _record_history(world):
    for rec_id in world.records.ids():
        rec = world.records.get(rec_id)
        assert rec.history, f"{rec.id} has no history"
        assert rec.history[0][0] == rec.created_day, f"{rec.id} creation day differs from history"
        assert rec.history[-1][1] == rec.state, f"{rec.id} history ends before current state"
        for previous, current in zip(rec.history, rec.history[1:]):
            if previous[1] == current[1]:
                continue  # lifecycle notes (for example, a repeated roll)
            assert (previous[1], current[1]) in LEGAL[rec.type], \
                f"{rec.id} illegal history transition {previous[1]} -> {current[1]}"


def _finished_goods(world):
    internal = {sku: sum(items.get(sku, 0) for items in world.stock.values()) for sku in PRODUCTS}
    for rec in world.records.all("booking"):
        if rec.state not in {"cancelled", "delivered"}:
            for sku, qty in rec.data["lines"].items(): internal[sku] += qty
    for rec in world.records.open("transfer"):
        for sku, qty in rec.data["lines"].items(): internal[sku] += qty
    for queue in world.dc_inbound_queue.values():
        for sku, qty in queue: internal[sku] += qty

    for sku in PRODUCTS:
        work_orders = [r for r in world.records.all("work_order") if r.data["sku"] == sku]
        attempted = sum(r.data["produced"] for r in work_orders)
        refs = {r.id for r in work_orders}
        unit_cost = component_cost(sku) + PRODUCTS[sku].assembly_cost
        scrap = round(sum(-amount for _, category, amount, ref in world.ledger.lines
                          if category == "writeoffs" and ref in refs) / unit_cost)
        produced = attempted - scrap
        shipped = sum(r.data.get("shipped_qty", 0) for r in world.records.all("order") if r.data["sku"] == sku)
        returns = [r for r in world.records.all("ret") if r.data["sku"] == sku]
        returned = sum(r.data["qty"] for r in returns)
        return_transit = sum(r.data["qty"] for r in returns if r.state == "in_transit")
        written_off = sum(r.data.get("written_off_qty", 0) for r in returns)
        lhs = world.opening_physical[sku] + produced
        rhs = internal[sku] + (shipped - returned) + return_transit + written_off
        assert lhs == rhs, f"{sku} conservation: {lhs} created/opening != {rhs} located/disposed"


def _components(world):
    for component in COMPONENTS:
        acquired = sum((po.data.get("shipped_qty") or 0) for po in world.records.all("po")
                       if po.data["component"] == component)
        on_hand = world.stock["PLANT"].get(component, 0)
        transit = sum((po.data.get("shipped_qty") or 0) for po in world.records.all("po")
                      if po.data["component"] == component and po.state == "shipped")
        quarantine = sum(lot.data.get("quarantined_qty", 0) for lot in world.records.all("lot")
                         if lot.data["component"] == component)
        wip = processed = 0
        for wo in world.records.all("work_order"):
            per = PRODUCTS[wo.data["sku"]].bom.get(component, 0)
            if not per: continue
            processed += wo.data["produced"] * per
            if wo.state not in {"complete", "cancelled"}:
                wip += (wo.data["qty"] - wo.data["produced"]) * per
        sorted_out = sum(lot.data["defects_true"] for lot in world.records.all("lot")
                         if lot.data["component"] == component and lot.state == "sorted")
        returned = sum(lot.data["qty"] for lot in world.records.all("lot")
                       if lot.data["component"] == component and lot.state == "returned")
        lhs = world.opening_physical[component] + acquired
        rhs = on_hand + transit + quarantine + wip + processed + sorted_out + returned
        assert lhs == rhs, f"{component} conservation: {lhs} acquired/opening != {rhs} located/used"


def _screen_boundary(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in HIDDEN or (key == "health" and "audit" in path and child is not None), \
                f"hidden screen key at {path + (key,)}"
            _screen_boundary(child, path + (key,))
    elif isinstance(value, (list, tuple)):
        for child in value: _screen_boundary(child, path)


def verify(world) -> None:
    for node, items in world.stock.items():
        for item, qty in items.items(): assert qty >= 0, f"negative stock: {node} {item}={qty}"
    for dc, items in world.allocated.items():
        for sku, qty in items.items():
            assert 0 <= qty <= world.stock[dc][sku], f"invalid allocation: {dc} {sku}={qty}"
    _record_history(world)
    cash_lines = sum(amount for _, category, amount, _ in world.ledger.lines
                     if category in CASH)
    assert abs(world.ledger.cash - (world.ledger.opening_cash + cash_lines)) < 1e-6, "cash ledger does not reconcile"
    _finished_goods(world)
    _components(world)
    _screen_boundary(world.screens())
