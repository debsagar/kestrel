from kestrel.world import World
from kestrel import calendar as cal
from datetime import date
import pytest

def days(w, n):
    for _ in range(n): w.end_day()

def test_booking_takes_plant_stock_and_charges_freight():
    w = World(1); w.add_stock("PLANT", "EB-STD", 9000); cash0 = w.ledger.cash
    r = w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": 8000}, "rate_type": "spot"})
    assert r["ok"] and w.stock["PLANT"]["EB-STD"] == 1000
    bk = w.records.get(r["id"])
    assert bk.data["containers"] == 1 and bk.data["freight"] > 1000 and bk.data["surcharges"] >= 500
    assert not w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": 5000}, "rate_type": "spot"})["ok"]


@pytest.mark.parametrize("qty", [-8000, 0, 8000.5, "8000", True])
def test_booking_rejects_non_positive_or_non_integer_lines_without_mutation(qty):
    w = World(1); w.add_stock("PLANT", "EB-STD", 9000)
    stock, freight, records = w.stock["PLANT"]["EB-STD"], w.ledger.total("freight"), len(w.records.all("booking"))
    result = w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": qty}})
    assert not result["ok"]
    assert (w.stock["PLANT"]["EB-STD"], w.ledger.total("freight"), len(w.records.all("booking"))) == (stock, freight, records)

def test_voyage_reaches_dc_nl():
    # Task 9 stops at the DC-NL inbound queue; Task 11 drains it into stock at 30
    # pallets/working day, so a small line (5 pallets) clears the queue the same day.
    w = World(2); w.add_stock("PLANT", "EB-PRO", 8000); nl0 = w.stock["DC-NL"]["EB-PRO"]
    r = w.apply({"type": "book_container", "mode": "air", "route": None, "lines": {"EB-PRO": 2000}, "rate_type": "spot"})
    days(w, 20)
    assert w.records.get(r["id"]).state == "delivered"
    assert w.dc_inbound_queue["DC-NL"] == []
    assert w.stock["DC-NL"]["EB-PRO"] == nl0 + 2000

def test_diverted_lane_slows_and_surcharges():
    w = World(3); w.cond._force_lane("diverted", 0); w.add_stock("PLANT", "EB-STD", 8000)
    r = w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": 8000}, "rate_type": "spot"})
    bk = w.records.get(r["id"]); assert bk.data["surcharges"] >= 1000
    days(w, 30); assert bk.state in ("cut_off", "rolled", "at_sea")
    days(w, 20); assert bk.state in ("at_sea", "arrived", "customs", "cleared", "delivered")

def test_contract_only_in_window():
    w = World(4)
    assert not w.apply({"type": "sign_freight_contract", "containers_per_month": 4})["ok"]
    while w.day < cal.to_day(date(2026, 5, 3)): w.end_day()
    r = w.apply({"type": "sign_freight_contract", "containers_per_month": 4}); assert r["ok"] and w.contract is not None
    w.add_stock("PLANT", "EB-STD", 8000)
    b = w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": 8000}, "rate_type": "contract"})
    assert b["ok"] and w.records.get(b["id"]).data["freight"] < w.cond.spot_rate()


@pytest.mark.parametrize("qty", [-4, 0, 4.9, "4", True])
def test_contract_rejects_non_positive_or_non_integer_quantity(qty):
    w = World(4)
    while w.day < cal.to_day(date(2026, 5, 3)): w.end_day()
    result = w.apply({"type": "sign_freight_contract", "containers_per_month": qty})
    assert not result["ok"] and w.contract is None

def test_demurrage_when_receiving_is_slow():
    w = World(5); w.add_stock("PLANT", "EB-STD", 8000)
    r = w.apply({"type": "book_container", "mode": "air", "route": None, "lines": {"EB-STD": 8000}, "rate_type": "spot"})
    w.dc_inbound_capacity["DC-NL"] = 0          # receiving stalled
    days(w, 25)
    assert w.ledger.total("demurrage") < 0


def test_rolled_booking_gets_exception_and_later_load():
    from kestrel.records import transition
    w = World(11); w.add_stock("PLANT", "EB-STD", 8000)
    r = w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": 8000}, "rate_type": "spot"})
    bk = w.records.get(r["id"])
    transition(bk, "cut_off", w.day, "test: force cut-off")
    bk.data["cutoff_day"] = w.day - 1                 # loading check fires today
    real_random = w.rng_ops.random
    w.rng_ops.random = lambda: 0.0                     # force the 8%/20% roll to hit
    w.end_day()
    w.rng_ops.random = real_random
    assert bk.state == "rolled"
    assert any(e["kind"] == "booking" and e["ref"] == bk.id for e in w.exceptions)
    assert any(st == "rolled" for _, st, _ in bk.history)
    bk.data["cutoff_day"] = w.day - 1                 # fire the loading check again, force success this time
    w.rng_ops.random = lambda: 0.99
    w.end_day()
    w.rng_ops.random = real_random
    assert bk.state == "at_sea"


def test_blank_sailing_delays_booking():
    w = World(12); w.add_stock("PLANT", "EB-STD", 8000)
    r = w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": 8000}, "rate_type": "spot"})
    bk = w.records.get(r["id"])
    orig_cutoff = bk.data["cutoff_day"]
    w.blank_sailings.append((orig_cutoff, orig_cutoff))
    w.end_day()
    assert bk.data["cutoff_day"] == orig_cutoff + 7
    assert any(st == "blanked" for _, st, _ in bk.history)
    assert bk.state == "cut_off"


def test_contract_minimum_charged_when_underused():
    w = World(13)
    while w.day < cal.to_day(date(2026, 5, 3)): w.end_day()
    assert w.apply({"type": "sign_freight_contract", "containers_per_month": 4})["ok"]
    before = w.ledger.total("freight")
    while cal.to_date(w.day).day != 1: w.end_day()
    w.end_day()                                        # the 1st: no bookings drew on the contract this month
    after = w.ledger.total("freight")
    assert after < before


def test_cancel_booking_returns_stock():
    w = World(14); w.add_stock("PLANT", "EB-STD", 8000)
    r = w.apply({"type": "book_container", "mode": "ocean", "route": "suez", "lines": {"EB-STD": 8000}, "rate_type": "spot"})
    assert w.stock["PLANT"]["EB-STD"] == 0
    c = w.apply({"type": "cancel_booking", "booking_id": r["id"]})
    assert c["ok"] and w.stock["PLANT"]["EB-STD"] == 8000
    assert w.records.get(r["id"]).state == "cancelled"


def test_port_strike_raises_queue_via_add_arrivals():
    w = World(15)
    w.cond.strike_until = w.day + 8
    before = w.cond.port_q
    w.cond.add_arrivals(100, w.day)
    assert w.cond.port_q - before == max(0, 100 - w.cond.port_capacity(w.day))
    assert w.cond.port_capacity(w.day) < 40                 # strike knocked capacity to 30%
