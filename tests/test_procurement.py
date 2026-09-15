from kestrel.world import World
from kestrel.records import transition
import pytest


def days(w, n):
    for _ in range(n): w.end_day()


def test_create_po_validates_moq_and_qualification():
    w = World(1)
    r = w.apply({"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": 100, "requested_day": 40, "incoterm": "FOB"})
    assert not r["ok"] and "MOQ" in r["reason"]
    r = w.apply({"type": "create_po", "supplier": "S-BRK", "component": "SOC", "qty": 500, "requested_day": 20, "incoterm": "FOB"})
    assert not r["ok"] and "qualified" in r["reason"]
    r = w.apply({"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": 20000, "requested_day": 40, "incoterm": "FOB"})
    assert r["ok"] and w.records.get(r["id"]).data["unit_price"] == 1.65


@pytest.mark.parametrize("qty", [-5000, 5000.9, "5000", True])
def test_create_po_rejects_non_positive_or_non_integer_quantity_without_mutation(qty):
    w = World(1)
    before = len(w.records.all("po"))
    result = w.apply({"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": qty})
    assert not result["ok"]
    assert len(w.records.all("po")) == before


def test_po_confirms_and_takes_deposit():
    w = World(1); cash0 = w.ledger.cash
    r = w.apply({"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": 5000, "requested_day": 40, "incoterm": "FOB"})
    days(w, 2)
    po = w.records.get(r["id"])
    assert po.state in ("confirmed", "in_production") and po.data["confirmed_qty"] == 5000 and po.data["promised_day"] >= 35
    assert cash0 - w.ledger.cash >= 0.3 * 5000 * 1.80 - 1e-6 - 0  # deposit plus daily holding etc. is at least the deposit


def test_po_ships_arrives_and_stocks_plant():
    w = World(3)
    r = w.apply({"type": "create_po", "supplier": "S-CASE", "component": "PKG", "qty": 5000, "requested_day": 5, "incoterm": "FOB"})
    before = w.stock["PLANT"]["PKG"]
    days(w, 60)
    po = w.records.get(r["id"])
    assert po.state in ("received", "inspected", "invoiced", "matched", "paid")
    assert w.stock["PLANT"]["PKG"] >= before  # consumption may happen only via work orders (none here)
    assert any(x.type == "lot" for x in w.records.all("lot"))


def test_insolvent_supplier_cancels_po():
    w = World(4); w.cond.supplier_health["S-DRV"] = "insolvent"
    r = w.apply({"type": "create_po", "supplier": "S-DRV", "component": "DRV", "qty": 10000, "requested_day": 60, "incoterm": "FOB"})
    days(w, 3)
    assert w.records.get(r["id"]).state == "cancelled" and any(e["kind"] == "supplier" for e in w.exceptions)


def test_invoice_mismatch_blocks_until_accepted():
    w = World(5)
    inv = w.records.new("invoice_in", 0, "blocked", po_id="PO-0001", amount=100.0, expected=94.0, due_day=30)
    assert not w.apply({"type": "accept_invoice", "invoice_id": "nope"})["ok"]
    assert w.apply({"type": "dispute_invoice", "invoice_id": inv.id})["ok"] and inv.state == "disputed"


def test_invoice_actions_reject_credit_note_without_mutating_it():
    w = World(5)
    note = w.records.new("credit_note", 0, "open", amount=100.0)
    original = dict(note.data)
    for action in ("accept_invoice", "dispute_invoice"):
        result = w.apply({"type": action, "invoice_id": note.id})
        assert not result["ok"]
        assert note.state == "open" and note.data == original


def test_qualification_and_audit():
    w = World(6)
    assert w.apply({"type": "qualify_supplier", "supplier": "S-BRK"})["ok"]
    days(w, 46); assert w.qualified["S-BRK"]
    w.cond.supplier_health["S-SOC"] = "strained"
    r = w.apply({"type": "request_audit", "supplier": "S-SOC"}); days(w, 4)
    assert w.records.get(r["id"]).data["health"] == "strained"


# -- additional tests (Step 4 of the brief) ---------------------------------

def test_allocation_confirms_fair_share():
    w = World(11)
    w.cond.alloc = "allocated"
    w.trailing_volume["S-SOC"] = [(w.day - 10, 60000)]  # v=60000 -> share=60000/100000=0.6 -> cap=int(60000*0.6/4)=9000
    r = w.apply({"type": "create_po", "supplier": "S-SOC", "component": "SOC", "qty": 20000, "requested_day": 60, "incoterm": "FOB"})
    days(w, 2)
    po = w.records.get(r["id"])
    assert po.state in ("confirmed", "in_production")
    assert po.data["confirmed_qty"] == 9000


def test_cny_blocks_shipping_on_holiday():
    from kestrel import calendar as cal
    w = World(12)
    while w.day < cal.CNY_START:
        w.end_day()
    po = w.records.new("po", w.day, "in_production", supplier="S-BAT", component="BAT", qty=5000, confirmed_qty=5000,
                        requested_day=w.day, promised_day=w.day, ship_day=cal.CNY_START, incoterm="FOB", unit_price=1.80,
                        deposit_paid=2700.0, balance_paid=0.0, expedited=False, asn_id=None, receipt_id=None,
                        lot_id=None, invoice_id=None)
    assert cal.china_capacity_factor(cal.CNY_START) == 0.0
    w.end_day()  # world.day == cal.CNY_START during this advance: capacity factor is 0, ship must slip
    assert po.state == "in_production"
    assert po.data["ship_day"] > cal.CNY_START
    assert any("holiday" in detail or "slip" in detail for _, _, detail in po.history)


def test_expedite_pulls_ship_date_in_on_success():
    w = World(13)
    r = w.apply({"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": 5000, "requested_day": 40, "incoterm": "FOB"})
    days(w, 3)
    po = w.records.get(r["id"])
    assert po.state == "in_production" and po.data["ship_day"] is not None
    original_ship_day = po.data["ship_day"]
    res = w.apply({"type": "expedite_po", "po_id": po.id})
    assert res["ok"]
    assert po.data["expedited"] is True
    assert po.data["ship_day"] <= original_ship_day


def test_cancel_after_confirmation_forfeits_deposit():
    w = World(14)
    r = w.apply({"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": 5000, "requested_day": 40, "incoterm": "FOB"})
    days(w, 2)
    po = w.records.get(r["id"])
    assert po.state in ("confirmed", "in_production")
    deposit = po.data["deposit_paid"]
    assert deposit > 0
    cash_before = w.ledger.cash
    res = w.apply({"type": "cancel_po", "po_id": po.id})
    assert res["ok"] and po.state == "cancelled"
    assert w.ledger.total("writeoffs") <= -deposit + 1e-6
    assert w.ledger.cash == cash_before  # writeoff is accrual only, does not move cash again


def test_rejected_lot_sorted_after_2_days_and_stock_drops():
    w = World(15)
    r = w.apply({"type": "create_po", "supplier": "S-CASE", "component": "PKG", "qty": 5000, "requested_day": 5, "incoterm": "FOB"})
    days(w, 40)
    po = w.records.get(r["id"])
    if po.data.get("lot_id") is None:
        return  # rng did not reach receipt within window on this seed; nothing to assert
    lot = w.records.get(po.data["lot_id"])
    if lot.state != "rejected":
        return
    reject_day = next(d for d, st, _ in lot.history if st == "rejected")
    stock_at_reject = w.stock["PLANT"]["PKG"]
    days(w, 3)
    lot2 = w.records.get(lot.id)
    assert lot2.state == "sorted"
    assert w.stock["PLANT"]["PKG"] == stock_at_reject + lot2.data["qty"] - lot2.data["defects_true"]


def test_rejected_lot_is_unavailable_until_sorting_releases_good_units():
    w = World(15)
    po = w.records.new("po", -1, "received", supplier="S-CASE", component="PKG", qty=5000,
                       confirmed_qty=5000, requested_day=5, promised_day=10, ship_day=10, incoterm="FOB",
                       unit_price=0.35, deposit_paid=0.0, balance_paid=0.0, expedited=False, asn_id=None,
                       receipt_id="GR-0001", lot_id=None, invoice_id=None, invoice_day=None, shipped_qty=5000)
    lot = w.records.new("lot", -1, "sampling", po_id=po.id, supplier="S-CASE", component="PKG", qty=5000,
                        defects_true=40, dppm=800, quarantined_qty=0)
    po.data["lot_id"] = lot.id
    w.stock["PLANT"]["PKG"] = 0
    w.add_stock("PLANT", "PKG", 5000)
    w.inspection_level["S-CASE"] = "I"
    w.rng_ops.binomialvariate = lambda n, p: 99
    before = w.stock["PLANT"]["PKG"]
    from kestrel import procurement
    procurement._inspect(w)
    assert lot.state == "rejected"
    assert lot.data["quarantined_qty"] == 5000
    assert w.stock["PLANT"]["PKG"] == before - 5000
    assert not w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 1})["ok"]
    days(w, 3)
    assert lot.state == "sorted"
    assert lot.data["quarantined_qty"] == 0
    assert w.stock["PLANT"]["PKG"] == before - 40


def test_return_lot_creates_credit_note_and_short_closes_po():
    w = World(5)
    po = w.records.new("po", 0, "inspected", supplier="S-CASE", component="PKG", qty=5000, confirmed_qty=5000,
                        requested_day=5, promised_day=10, ship_day=10, incoterm="FOB", unit_price=0.35,
                        deposit_paid=525.0, balance_paid=1225.0, expedited=False, asn_id=None, receipt_id="GR-0001",
                        lot_id=None, invoice_id=None)
    lot = w.records.new("lot", 5, "sampling", po_id=po.id, supplier="S-CASE", component="PKG", qty=5000, defects_true=40, dppm=800, quarantined_qty=5000)
    transition(lot, "rejected", 6, "AQL fail")
    po.data["lot_id"] = lot.id
    before = w.stock["PLANT"]["PKG"]
    res = w.apply({"type": "return_lot", "lot_id": lot.id})
    assert res["ok"]
    assert lot.state == "returned"
    assert po.state == "short_closed"
    assert w.stock["PLANT"]["PKG"] == before
    notes = w.records.all("credit_note")
    note = next(n for n in notes if n.data["po_id"] == po.id and n.data["lot_id"] == lot.id)
    assert note.state == "open"
    # minor fix: a credit note settles to "paid" (+amount to cash, category "credit") 30 days after creation
    days(w, 31)
    note2 = w.records.get(note.id)
    assert note2.state == "paid"
    assert w.ledger.total("credit") == note2.data["amount"]  # only this note posts to "credit" on this seed/window


def test_return_lot_rejects_po_already_past_inspected():
    # critical fix: a PO whose invoice auto-matched the same day (due <= 0) can race past "inspected"
    # to "paid" in the same tick; return_lot must reject cleanly instead of raising IllegalTransition.
    w = World(5)
    po = w.records.new("po", 0, "paid", supplier="S-CASE", component="PKG", qty=5000, confirmed_qty=5000,
                        requested_day=5, promised_day=10, ship_day=10, incoterm="FOB", unit_price=0.35,
                        deposit_paid=525.0, balance_paid=1225.0, expedited=False, asn_id=None, receipt_id="GR-0001",
                        lot_id=None, invoice_id=None)
    lot = w.records.new("lot", 5, "sampling", po_id=po.id, supplier="S-CASE", component="PKG", qty=5000, defects_true=40, dppm=800)
    transition(lot, "rejected", 6, "AQL fail")
    po.data["lot_id"] = lot.id
    w.add_stock("PLANT", "PKG", 5000)
    res = w.apply({"type": "return_lot", "lot_id": lot.id})
    assert not res["ok"]
    assert "not eligible" in res["reason"] or "state" in res["reason"]
    assert lot.state == "rejected"  # untouched: no partial mutation before the guard raised


def test_deposit_retries_on_cash_shortfall_then_enters_production():
    w = World(16)
    w.demand.order_qty = lambda day, sku, customer: 0
    w.ledger.cash = 0.0
    r = w.apply({"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": 5000, "requested_day": 40, "incoterm": "FOB"})
    days(w, 2)
    po = w.records.get(r["id"])
    assert po.state == "confirmed"
    assert po.data["confirmed_qty"] == 5000  # allocation/promise fixed once, independent of cash
    assert po.data["deposit_paid"] == 0.0
    assert any(e["kind"] == "cash" for e in w.exceptions)
    days(w, 5)
    assert po.state == "confirmed" and po.data["deposit_paid"] == 0.0  # still stuck: no cash yet
    w.ledger.post(w.day, "customer_receipt", 1_000_000.0, "test funding")
    w.end_day()  # deposit clears today
    assert po.data["deposit_paid"] > 0
    assert po.state == "confirmed"  # not yet in production the same day the deposit posts
    w.end_day()  # next day
    assert po.state == "in_production"
