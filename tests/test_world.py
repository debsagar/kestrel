import pytest
from kestrel.world import World

def test_reset_positions():
    w = World(1)
    # Task 8's seed_opening posts real opening-PO deposits on day 0 (SPEC S5.1 ruling 5), so cash
    # starts below the nominal opening balance rather than exactly at it.
    assert w.day == 0 and 0 < w.ledger.cash < 2_500_000
    assert w.stock["DC-DE"]["EB-STD"] > 0 and w.stock["PLANT"]["SOC"] > 0 and w.stock["PLANT"].get("EB-STD", 0) == 0

def test_stock_helpers():
    w = World(1); w.add_stock("DC-PL", "SPK-1", 10); w.take_stock("DC-PL", "SPK-1", 4)
    assert w.stock["DC-PL"]["SPK-1"] - 6 == World(1).stock["DC-PL"]["SPK-1"]
    with pytest.raises(ValueError): w.take_stock("DC-PL", "SPK-1", 10**9)

def test_unknown_action_rejected_and_end_day_advances():
    w = World(2)
    r = w.apply({"type": "teleport"})
    assert r["ok"] is False and "unknown" in r["reason"]
    rep = w.end_day()
    assert w.day == 1 and rep["day"] == 0 and "cash" in rep

@pytest.mark.parametrize("action", [None, [], "book_container", {"type": []}])
def test_malformed_action_is_rejected_without_mutation(action):
    w = World(2)
    before = w.export()
    result = w.apply(action)
    assert result["ok"] is False
    assert w.export() == before

def test_same_seed_same_world():
    a, b = World(9), World(9)
    for _ in range(30): a.end_day(); b.end_day()
    assert a.export()["hidden"] == b.export()["hidden"] and a.ledger.cash == b.ledger.cash
