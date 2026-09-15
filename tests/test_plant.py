from kestrel.world import World
from kestrel import calendar as cal
from datetime import date
import pytest


def test_release_needs_components_and_consumes_them():
    w = World(1); soc = w.stock["PLANT"]["SOC"]
    assert not w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 10**7})["ok"]
    r = w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 1000}); assert r["ok"]
    assert w.stock["PLANT"]["SOC"] == soc - 1000 and w.stock["PLANT"]["DRV"] == World(1).stock["PLANT"]["DRV"] - 2000


@pytest.mark.parametrize("qty", [-1, 0, 1.9, "1", True])
def test_release_rejects_non_positive_or_non_integer_quantity_without_mutation(qty):
    w = World(1)
    stock, consumed = dict(w.stock["PLANT"]), w.flows["consumed_components"]
    result = w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": qty})
    assert not result["ok"]
    assert w.stock["PLANT"] == stock and w.flows["consumed_components"] == consumed
    assert not w.records.all("work_order")


def test_capacity_changeover_and_yield():
    w = World(2)
    w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 3000})
    w.apply({"type": "release_work_order", "sku": "SPK-1", "qty": 1000})
    w.end_day()   # day 0 is a Monday: 4000 eq capacity: 3000 EB-STD, changeover 400, then 300 speakers (600 eq)
    assert w.stock["PLANT"]["EB-STD"] == round(3000 * 0.98 * (1 - 800 / 1e6))
    assert w.records.all("work_order")[1].data["produced"] == 300
    w.end_day(); assert w.records.all("work_order")[1].state == "complete"


def test_cny_stops_the_line():
    w = World(3)
    while w.day < cal.to_day(date(2026, 2, 16)): w.end_day()
    w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 500}); w.end_day()
    assert w.records.all("work_order")[-1].data["produced"] == 0


def test_cancel_returns_components():
    w = World(4)
    soc_before = w.stock["PLANT"]["SOC"]
    r = w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 1000})
    assert w.stock["PLANT"]["SOC"] == soc_before - 1000
    c = w.apply({"type": "cancel_work_order", "work_order_id": r["id"]})
    assert c["ok"]
    assert w.stock["PLANT"]["SOC"] == soc_before
    assert w.records.get(r["id"]).state == "cancelled"


def test_sunday_produces_nothing():
    w = World(5)
    # advance to a Sunday
    while cal.weekday(w.day) != 6:
        w.end_day()
    r = w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 500})
    assert r["ok"]
    produced_before = w.records.get(r["id"]).data["produced"]
    w.end_day()
    assert w.records.get(r["id"]).data["produced"] == produced_before == 0


def test_flows_counters_move():
    w = World(6)
    r = w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 1000})
    assert w.flows["consumed_components"] == 7000  # bom qty-per-unit sums to 7 (BAT1+SOC1+DRV2+CASE1+CHG1+PKG1) x 1000
    produced_before = w.flows["produced"]
    w.end_day()
    assert w.flows["produced"] > produced_before


def test_production_posts_only_scrap_writeoff_not_cogs():
    w = World(7)
    w.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 1000})
    w.end_day()
    assert w.ledger.total("cogs_components") == 0
    assert w.ledger.total("cogs_assembly") == 0
    assert w.ledger.total("writeoffs") < 0
