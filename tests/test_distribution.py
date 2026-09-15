from copy import deepcopy

import pytest

from kestrel.world import World


def test_transfer_moves_stock_with_lead_time_and_cost():
    w = World(1); w.demand.order_qty = lambda day, sku, customer: 0
    w.stock["DC-NL"]["EB-STD"] = 5000; de0 = w.stock["DC-DE"]["EB-STD"]
    r = w.apply({"type": "create_transfer", "src": "DC-NL", "dst": "DC-DE", "mode": "rail", "lines": {"EB-STD": 800}})
    assert r["ok"] and w.stock["DC-NL"]["EB-STD"] == 4200 and w.ledger.total("inter_dc") == -180.0
    w.end_day(); w.end_day()
    assert w.stock["DC-DE"]["EB-STD"] == de0 + 800


def test_invalid_leg_and_insufficient_stock():
    w = World(2)
    assert not w.apply({"type": "create_transfer", "src": "DC-PL", "dst": "DC-NL", "mode": "rail", "lines": {"EB-STD": 1}})["ok"]
    assert not w.apply({"type": "create_transfer", "src": "DC-NL", "dst": "DC-DE", "mode": "rail", "lines": {"EB-STD": 10**7}})["ok"]


def test_transfer_cannot_take_customer_reserved_stock():
    w = World(2)
    w.stock["DC-DE"]["EB-STD"] = 100
    w.allocated["DC-DE"]["EB-STD"] = 80
    result = w.apply({"type": "create_transfer", "src": "DC-DE", "dst": "DC-PL", "mode": "truck",
                      "lines": {"EB-STD": 21}})
    assert not result["ok"]
    assert w.stock["DC-DE"]["EB-STD"] == 100


@pytest.mark.parametrize("lines", [
    {"EB-STD": True},
    {"EB-STD": 1.5},
    {"EB-STD": "1"},
    [("EB-STD", 1)],
    "EB-STD=1",
])
def test_invalid_transfer_lines_leave_world_unchanged(lines):
    w = World(7)
    before = (
        deepcopy(w.stock),
        deepcopy(w.records.__dict__),
        deepcopy(w.ledger.__dict__),
        list(w.day_log),
        w.rng_ops.getstate(),
    )

    result = w.apply({"type": "create_transfer", "src": "DC-NL", "dst": "DC-DE", "mode": "rail", "lines": lines})

    assert not result["ok"]
    assert (
        w.stock,
        w.records.__dict__,
        w.ledger.__dict__,
        w.day_log,
        w.rng_ops.getstate(),
    ) == before


def test_receiving_capacity_limits_daily_intake():
    w = World(3); w.stock["DC-NL"]["EB-STD"] = 100000; de0 = w.stock["DC-DE"]["EB-STD"]
    w.apply({"type": "create_transfer", "src": "DC-NL", "dst": "DC-DE", "mode": "rail", "lines": {"EB-STD": 40000}})  # 100 pallets
    w.end_day(); w.end_day()
    assert w.stock["DC-DE"]["EB-STD"] - de0 <= 30 * 400 + 0 and len(w.dc_inbound_queue["DC-DE"]) >= 1


def test_logistics_container_lands_in_dc_stock_next_working_day():
    """A container delivered by logistics (Task 9) puts (sku, qty) into the queue by hand;
    distribution drains it into DC-NL stock on the next DC working day."""
    w = World(4)
    nl0 = w.stock["DC-NL"]["EB-STD"]
    w.dc_inbound_queue["DC-NL"].append(("EB-STD", 500))
    w.end_day()  # day 0 (Mon) -> day 1 (Tue), a DC working day
    assert w.stock["DC-NL"]["EB-STD"] == nl0 + 500
    assert w.dc_inbound_queue["DC-NL"] == []


def test_weekend_queue_waits():
    w = World(5)
    # Advance to Saturday of week 1 (day 5), then queue a container after end-of-day.
    for _ in range(5):
        w.end_day()
    assert w.day == 5  # Saturday
    nl0 = w.stock["DC-NL"]["EB-STD"]
    w.dc_inbound_queue["DC-NL"].append(("EB-STD", 300))
    w.end_day()  # day 5 (Sat) -> day 6 (Sun): not a DC working day, queue waits
    assert w.stock["DC-NL"]["EB-STD"] == nl0
    assert w.dc_inbound_queue["DC-NL"] == [("EB-STD", 300)]
    w.end_day()  # day 6 (Sun) -> day 7 (Mon): still waits (advance ran on day 6, Sunday)
    assert w.stock["DC-NL"]["EB-STD"] == nl0
    w.end_day()  # day 7 (Mon) -> day 8: delivered
    assert w.stock["DC-NL"]["EB-STD"] == nl0 + 300


def test_oversized_queue_raises_dc_exception_once():
    w = World(6)
    # capacity default 30 pallets/day, per_pallet 400 -> 3x capacity = 90 pallets = 36000 units
    w.dc_inbound_queue["DC-NL"].append(("EB-STD", 40000))  # 100 pallets, over the 90-pallet threshold
    w.end_day()
    dc_exceptions = [e for e in w.exceptions if e["kind"] == "dc" and e["ref"] == "DC-NL"]
    assert len(dc_exceptions) == 1
