"""Purchase orders from draft to paid: confirmation, deposits, ASN, receipt, AQL inspection, invoices (SPEC S5.1, S6.4).

Health is hidden: only request_audit copies it into a record, and _confirm may test for
insolvency (the supplier's silence is itself an observable signal), per the task-8 ruling.
"""
from . import calendar as cal
from .aql import AQL_SAMPLE, ACCEPT, sample_plan as _sample_plan  # noqa: F401 (AQL_SAMPLE/ACCEPT re-exported: task-8 interface)
from .network import SUPPLIERS, PRODUCTS, COMPONENTS, PRIMARY_SUPPLIER, price_for
from .records import transition

def po_value(rec) -> float:
    return rec.data["confirmed_qty"] * rec.data["unit_price"]

def _update_component_dppm(world, component: str) -> None:
    """Ruling 4: quantity-weighted trailing dppm of the last 5 accepted/sorted lots of a component."""
    lots = [l for l in world.records.all("lot") if l.data["component"] == component and l.state in ("accepted", "sorted")]
    lots.sort(key=lambda l: l.history[-1][0])
    last5 = lots[-5:]
    total = sum(l.data["qty"] for l in last5)
    if total:
        world.component_dppm[component] = sum(l.data["qty"] * (0 if l.state == "sorted" else l.data["dppm"]) for l in last5) / total

# -- planner actions ----------------------------------------------------------

def create_po(world, a):
    s, c = a.get("supplier"), a.get("component")
    if s is None: raise ValueError("supplier is required")
    if c is None: raise ValueError("component is required")
    if s not in SUPPLIERS: raise ValueError(f"unknown supplier {s!r}")
    if c not in SUPPLIERS[s].components: raise ValueError(f"{s} does not supply {c}")
    if "qty" not in a: raise ValueError("qty is required")
    qty = a["qty"]
    if type(qty) is not int or qty <= 0:
        raise ValueError(f"qty must be a positive integer, got {qty!r}")
    moq = SUPPLIERS[s].moq[c]
    if qty < moq: raise ValueError(f"qty {qty} is below MOQ {moq} for {c} at {s}")
    if not world.qualified[s]: raise ValueError(f"{s} is not a qualified supplier; run qualify_supplier first (45 days)")
    price = price_for(s, c, qty)
    if world.cond.alloc == "allocated" and s == "S-BRK": price *= 1.8
    requested_day = int(a.get("requested_day", world.day + 30))
    rec = world.records.new(
        "po", world.day, "draft", supplier=s, component=c, qty=qty, confirmed_qty=0, requested_day=requested_day,
        promised_day=None, ship_day=None, incoterm=a.get("incoterm", "FOB"), unit_price=price, deposit_paid=0.0,
        balance_paid=0.0, expedited=False, asn_id=None, receipt_id=None, lot_id=None, invoice_id=None,
        confirm_day=world.day + 1 + world.cond.confirm_lag(s), arrival_day=None, shipped_qty=None, invoice_day=None,
    )
    world.log(f"PO {rec.id}: {qty} {c} from {s} at {price:.2f}")
    return {"id": rec.id}

def _get_po(world, a):
    po_id = a.get("po_id")
    if not po_id: raise ValueError("po_id is required")
    try: return world.records.get(po_id)
    except KeyError: raise KeyError(f"no such PO {po_id!r}")

def cancel_po(world, a):
    po = _get_po(world, a)
    if po.state not in ("draft", "confirmed", "in_production"):
        raise ValueError(f"PO {po.id} cannot be cancelled from state {po.state!r}")
    if po.state in ("confirmed", "in_production") and po.data["deposit_paid"] > 0:
        world.ledger.post(world.day, "writeoffs", -po.data["deposit_paid"], po.id)
    transition(po, "cancelled", world.day, "cancelled by planner")
    return {"id": po.id}

def expedite_po(world, a):
    po = _get_po(world, a)
    if po.state not in ("confirmed", "in_production"):
        raise ValueError(f"PO {po.id} cannot be expedited from state {po.state!r}")
    if po.data["expedited"]: raise ValueError(f"PO {po.id} is already expedited")
    value = po_value(po) if po.data["confirmed_qty"] else po.data["qty"] * po.data["unit_price"]
    world.ledger.post(world.day, "expedite", -0.05 * value, po.id)
    po.data["expedited"] = True
    s = po.data["supplier"]
    prob = 0.0 if world.cond.otif(s) <= 0.65 else 0.6  # otif() is the only permitted read of health-derived state here
    if world.rng_ops.random() < prob:
        if po.data["ship_day"] is not None:
            pull = min(7, po.data["ship_day"] - world.day - 1)
            if pull > 0: po.data["ship_day"] -= pull
        else:
            pull = min(7, po.data["promised_day"] - world.day - 1)
            if pull > 0: po.data["promised_day"] -= pull
        po.history.append((world.day, po.state, f"expedite succeeded, pulled in {max(pull, 0)}d"))
    else:
        po.history.append((world.day, po.state, "expedite failed"))
    return {"id": po.id}

def set_inspection_level(world, a):
    s = a.get("supplier")
    if s not in SUPPLIERS: raise ValueError(f"unknown supplier {s!r}")
    level = a.get("level")
    if level not in ("I", "II", "III"): raise ValueError(f"level must be I, II, or III, got {level!r}")
    world.inspection_level[s] = level
    return {"id": s}

def qualify_supplier(world, a):
    s = a.get("supplier")
    if s not in SUPPLIERS: raise ValueError(f"unknown supplier {s!r}")
    if world.qualified[s]: raise ValueError(f"{s} is already qualified")
    rec = world.records.new("qualification", world.day, "pending", supplier=s, done_day=world.day + 45)
    return {"id": rec.id}

def request_audit(world, a):
    s = a.get("supplier")
    if s not in SUPPLIERS: raise ValueError(f"unknown supplier {s!r}")
    rec = world.records.new("audit", world.day, "pending", supplier=s, done_day=world.day + 3, health=None)
    world.ledger.post(world.day, "audits", -2000.0, rec.id)
    return {"id": rec.id}

def return_lot(world, a):
    lot_id = a.get("lot_id")
    if not lot_id: raise ValueError("lot_id is required")
    try: lot = world.records.get(lot_id)
    except KeyError: raise KeyError(f"no such lot {lot_id!r}")
    if lot.state != "rejected": raise ValueError(f"lot {lot.id} cannot be returned from state {lot.state!r}")
    po = world.records.get(lot.data["po_id"])
    if po.state not in ("received", "inspected"):
        raise ValueError(f"PO {po.id} is not eligible for a lot return (state={po.state!r})")
    qty, c, s = lot.data["qty"], lot.data["component"], lot.data["supplier"]
    quarantined = lot.data.get("quarantined_qty", 0)
    if quarantined:
        if quarantined != qty:
            raise ValueError(f"lot {lot.id} has an invalid quarantined quantity")
        lot.data["quarantined_qty"] = 0
    else:
        # Compatibility for rejected lots created before quarantine was tracked.
        world.take_stock("PLANT", c, qty)
    note = world.records.new("credit_note", world.day, "open", po_id=po.id, lot_id=lot.id, supplier=s, component=c,
                              qty=qty, amount=qty * po.data["unit_price"])
    transition(lot, "returned", world.day, "returned to supplier")
    transition(po, "short_closed", world.day, "lot returned to supplier")
    world.flows["returned_lots"] += 1
    return {"id": note.id}

def _get_invoice(world, a):
    inv_id = a.get("invoice_id")
    if not inv_id: raise ValueError("invoice_id is required")
    try: inv = world.records.get(inv_id)
    except KeyError: raise KeyError(f"no such invoice {inv_id!r}")
    if inv.type != "invoice_in": raise ValueError(f"record {inv_id!r} is not an inbound invoice")
    return inv

def _settle_invoice(world, inv):
    """Pay any residual after deposit+balance, mark invoice paid, and close the PO if it exists."""
    po = None
    if inv.data.get("po_id"):
        try: po = world.records.get(inv.data["po_id"])
        except KeyError: po = None
    due = inv.data["amount"] - (po.data["deposit_paid"] + po.data["balance_paid"] if po else 0.0)
    if due > 0: world.ledger.post(world.day, "supplier_payment", -due, inv.id)
    transition(inv, "paid", world.day, "paid")
    if po is not None and po.state == "invoiced":
        transition(po, "matched", world.day, "matched")
        transition(po, "paid", world.day, "paid")

def accept_invoice(world, a):
    inv = _get_invoice(world, a)
    if inv.state not in ("open", "blocked"): raise ValueError(f"invoice {inv.id} not awaiting acceptance (state={inv.state})")
    transition(inv, "accepted", world.day, "accepted by planner")
    _settle_invoice(world, inv)
    return {"id": inv.id}

def dispute_invoice(world, a):
    inv = _get_invoice(world, a)
    if inv.state not in ("open", "blocked"): raise ValueError(f"invoice {inv.id} not disputable (state={inv.state})")
    inv.data["dispute_day"] = world.day
    transition(inv, "disputed", world.day, "disputed by planner")
    return {"id": inv.id}

ACTIONS = {
    "create_po": create_po, "cancel_po": cancel_po, "expedite_po": expedite_po,
    "accept_invoice": accept_invoice, "dispute_invoice": dispute_invoice,
    "set_inspection_level": set_inspection_level, "qualify_supplier": qualify_supplier,
    "request_audit": request_audit, "return_lot": return_lot,
}

# -- daily lifecycle stages -----------------------------------------------------

def _try_deposit(world, po):
    """Attempt to post the deposit for a confirmed PO; retried daily by _start_production until it clears.
    Appends a history note on success so the 'next day' gate in _start_production restarts from that day."""
    if po.data["deposit_paid"] > 0: return True
    deposit = SUPPLIERS[po.data["supplier"]].deposit_pct * po_value(po)
    if deposit > 0 and world.ledger.cash < deposit:
        world.exception("cash", po.id, f"insufficient cash for deposit on {po.id}")
        return False
    if deposit > 0: world.ledger.post(world.day, "deposit", -deposit, po.id)
    po.data["deposit_paid"] = deposit
    po.history.append((world.day, po.state, "deposit posted"))
    return True

def _confirm(world):
    for po in world.records.open("po"):
        if po.state != "draft": continue
        s = po.data["supplier"]
        if world.cond.supplier_health[s] == "insolvent":
            transition(po, "cancelled", world.day, "supplier insolvent")
            world.exception("supplier", po.id, f"{s} is insolvent; PO cancelled")
            continue
        if world.day < po.data["confirm_day"]: continue
        c, qty = po.data["component"], po.data["qty"]
        if world.cond.alloc == "allocated" and s == "S-SOC":
            v = sum(q for d, q in world.trailing_volume[s] if d >= world.day - 90)
            share = v / (v + 40000)
            confirmed = min(qty, int(60000 * share / 4))
            moq = SUPPLIERS[s].moq[c]
            if 0 < confirmed < moq: confirmed = min(qty, moq)
        else:
            confirmed = qty
        po.data["confirmed_qty"] = confirmed
        po.data["promised_day"] = max(po.data["requested_day"], world.day + world.cond.quoted_lead(s, c))
        # confirmed_qty/promised_day are fixed here, once, regardless of cash; the deposit is a separate,
        # daily-retried concern owned by _start_production so a cash-poor day never re-rolls allocation.
        transition(po, "confirmed", world.day, "confirmed")
        world.log(f"PO {po.id}: confirmed {confirmed} units, promised {po.data['promised_day']}")

def _start_production(world):
    for po in world.records.open("po"):
        if po.state != "confirmed": continue
        if po.data["deposit_paid"] <= 0 and not _try_deposit(world, po): continue
        if world.day <= po.history[-1][0]: continue
        s = po.data["supplier"]
        slip = 0 if world.rng_ops.random() < world.cond.otif(s) else world.rng_ops.randint(3, 14)
        if world.cond.alloc == "allocated" and s == "S-SOC": slip *= 2
        po.data["ship_day"] = po.data["promised_day"] + slip
        transition(po, "in_production", world.day, "in production")

def _ship(world):
    for po in world.records.open("po"):
        if po.state != "in_production" or world.day < po.data["ship_day"]: continue
        factor = cal.china_capacity_factor(world.day)
        if factor == 0.0:
            po.data["ship_day"] += 1
            po.history.append((world.day, po.state, "ship slipped: China capacity holiday"))
            continue
        if factor < 1.0 and world.rng_ops.random() >= factor:
            po.data["ship_day"] += 1
            po.history.append((world.day, po.state, f"ship slipped: China capacity ramp ({factor:.2f})"))
            continue
        s = po.data["supplier"]
        confirmed = po.data["confirmed_qty"]
        shipped = confirmed
        if world.rng_ops.random() < world.cond.short_ship_prob(s):
            shipped = int(confirmed * world.rng_ops.uniform(0.6, 0.9))
        po.data["shipped_qty"] = shipped
        world.ledger.post(world.day, "balance", -(1 - SUPPLIERS[s].deposit_pct) * po_value(po), po.id)
        po.data["balance_paid"] = (1 - SUPPLIERS[s].deposit_pct) * po_value(po)
        po.data["arrival_day"] = world.day + SUPPLIERS[s].road_days
        asn = world.records.new("asn", world.day, "sent", po_id=po.id, supplier=s, component=po.data["component"], qty=shipped)
        po.data["asn_id"] = asn.id
        transition(po, "shipped", world.day, "shipped")

def _receive(world):
    for po in world.records.open("po"):
        if po.state != "shipped" or world.day < po.data["arrival_day"]: continue
        s, c, qty = po.data["supplier"], po.data["component"], po.data["shipped_qty"]
        world.add_stock("PLANT", c, qty)
        world.flows["received_components"] += qty
        receipt = world.records.new("receipt", world.day, "received", po_id=po.id, supplier=s, component=c, qty=qty)
        po.data["receipt_id"] = receipt.id
        dppm = world.cond.dppm(s)
        if s == "S-BRK" and world.cond.alloc == "allocated" and world.rng_ops.random() < 0.3: dppm = 10000
        defects_true = world.rng_ops.binomialvariate(qty, min(1.0, dppm / 1e6)) if qty else 0
        lot = world.records.new("lot", world.day, "sampling", po_id=po.id, supplier=s, component=c, qty=qty,
                                 defects_true=defects_true, dppm=dppm, quarantined_qty=0)
        po.data["lot_id"] = lot.id
        world.trailing_volume[s].append((world.day, qty))
        world.trailing_volume[s][:] = [(d, q) for d, q in world.trailing_volume[s] if d >= world.day - 90]
        transition(po, "received", world.day, "received")

def _inspect(world):
    for po in world.records.open("po"):
        if po.state != "received" or world.day <= po.history[-1][0]: continue
        lot = world.records.get(po.data["lot_id"])
        level = world.inspection_level[po.data["supplier"]]
        sample, accept_num = _sample_plan(lot.data["qty"], level)
        p = lot.data["defects_true"] / lot.data["qty"] if lot.data["qty"] else 0.0
        sampled_defects = world.rng_ops.binomialvariate(sample, min(1.0, p)) if sample else 0
        world.ledger.post(world.day, "inspection", -0.05 * sample, po.id)
        if sampled_defects <= accept_num:
            transition(lot, "accepted", world.day, "AQL pass")
            _update_component_dppm(world, lot.data["component"])
        else:
            world.take_stock("PLANT", lot.data["component"], lot.data["qty"])
            lot.data["quarantined_qty"] = lot.data["qty"]
            transition(lot, "rejected", world.day, "AQL fail")
            world.exception("quality", lot.id, f"lot {lot.id} rejected: {sampled_defects} defects in sample of {sample} (accept {accept_num})")
        po.data["invoice_day"] = world.day + world.rng_ops.randint(0, 5)
        transition(po, "inspected", world.day, "inspected")
    for lot in world.records.open("lot"):
        if lot.state != "rejected": continue
        reject_day = lot.history[-1][0]
        if world.day < reject_day + 2: continue
        good_qty = lot.data["qty"] - lot.data["defects_true"]
        world.add_stock("PLANT", lot.data["component"], good_qty)
        lot.data["quarantined_qty"] = 0
        world.ledger.post(world.day, "inspection", -0.40 * lot.data["qty"], lot.id)
        transition(lot, "sorted", world.day, "sorted")
        world.flows["sorted_out"] += lot.data["defects_true"]
        _update_component_dppm(world, lot.data["component"])

def _invoice(world):
    for po in world.records.open("po"):
        if po.state != "inspected" or world.day < po.data["invoice_day"]: continue
        s, qty = po.data["supplier"], po.data["shipped_qty"]
        expected = po.data["unit_price"] * qty
        mismatch = world.rng_ops.random() < 0.08
        amount = expected * 1.06 if mismatch else expected
        inv = world.records.new("invoice_in", world.day, "blocked" if mismatch else "open", po_id=po.id, supplier=s,
                                 amount=amount, expected=expected, due_day=world.day + 30)
        po.data["invoice_id"] = inv.id
        transition(po, "invoiced", world.day, "invoiced")
        if mismatch:
            world.exception("invoice", inv.id, f"invoice {inv.id} mismatches PO {po.id}: {amount:.2f} vs {expected:.2f}")
            continue
        due = inv.data["amount"] - (po.data["deposit_paid"] + po.data["balance_paid"])
        if due <= 0:
            transition(inv, "accepted", world.day, "auto-matched: fully covered by deposit+balance")
            _settle_invoice(world, inv)

def _settle(world):
    for inv in world.records.all("invoice_in"):
        if inv.state != "disputed" or world.day < inv.data["dispute_day"] + 10: continue
        inv.data["amount"] *= 0.94
        transition(inv, "accepted", world.day, "dispute resolved at -6%")
        _settle_invoice(world, inv)
    for note in world.records.all("credit_note"):
        if note.state == "open" and note.created_day + 30 <= world.day:
            world.ledger.post(world.day, "credit", note.data["amount"], note.id)
            transition(note, "paid", world.day, "supplier credit settled")

def _qualifications(world):
    for q in world.records.open("qualification"):
        if world.day >= q.data["done_day"]:
            world.qualified[q.data["supplier"]] = True
            transition(q, "done", world.day, "qualified")

def _audits(world):
    for au in world.records.open("audit"):
        if world.day >= au.data["done_day"]:
            au.data["health"] = world.cond.supplier_health[au.data["supplier"]]
            transition(au, "done", world.day, "audit complete")

def _scorecards(world):
    if cal.to_date(world.day).day != 1: return
    for s in SUPPLIERS:
        pos = [po for po in world.records.all("po") if po.data["supplier"] == s and po.data.get("receipt_id")]
        window = []
        for po in pos:
            receipt_day = next((d for d, st, _ in po.history if st == "received"), None)
            if receipt_day is not None and world.day - 30 <= receipt_day <= world.day:
                window.append((po, receipt_day))
        if window:
            on_time = sum(1 for po, rd in window if rd <= po.data["promised_day"] + SUPPLIERS[s].road_days)
            otif_30d = on_time / len(window)
            total_qty = sum(w_po.data["shipped_qty"] for w_po, _ in window)
            ppm_30d = sum(world.records.get(w_po.data["lot_id"]).data["dppm"] * w_po.data["shipped_qty"]
                          for w_po, _ in window if w_po.data.get("lot_id")) / total_qty if total_qty else 0.0
        else:
            otif_30d, ppm_30d = 0.0, 0.0
        world.scorecards[s] = {"otif_30d": otif_30d, "ppm_30d": ppm_30d, "updated_day": world.day}

def advance(world):
    _confirm(world)
    _start_production(world)
    _ship(world)
    _receive(world)
    _inspect(world)
    _invoice(world)
    _settle(world)
    _qualifications(world)
    _audits(world)
    _scorecards(world)

def seed_opening(world):
    for i, c in enumerate(COMPONENTS):
        s = PRIMARY_SUPPLIER[c]
        raw = int(sum(world.demand.expected(0, sku) * p.bom.get(c, 0) for sku, p in PRODUCTS.items()) * 45)
        qty = max(raw, SUPPLIERS[s].moq[c])
        price = price_for(s, c, qty)
        ship_day = 10 + i * 3
        rec = world.records.new(
            "po", 0, "in_production", supplier=s, component=c, qty=qty, confirmed_qty=qty, requested_day=0,
            promised_day=ship_day, ship_day=ship_day, incoterm="FOB", unit_price=price, deposit_paid=0.0,
            balance_paid=0.0, expedited=False, asn_id=None, receipt_id=None, lot_id=None, invoice_id=None,
            confirm_day=None, arrival_day=None, shipped_qty=None, invoice_day=None,
        )
        deposit = SUPPLIERS[s].deposit_pct * po_value(rec)
        world.ledger.post(0, "deposit", -deposit, rec.id)
        rec.data["deposit_paid"] = deposit
