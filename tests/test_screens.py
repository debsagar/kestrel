import copy
import json

from kestrel.screens import HIDDEN, build, record_view
from kestrel.world import World


def walk(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path + (key,)
            yield from walk(child, path + (key,))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child, path)


def test_screens_are_complete_serialisable_and_read_only():
    world = World(1)
    for _ in range(15): world.end_day()
    before, rng = copy.deepcopy(world.export()), world.rng_ops.getstate()
    screen = build(world)
    assert set(screen) == {"calendar", "inventory", "records", "exceptions", "news", "market",
                           "suppliers", "customers", "finance", "forecast"}
    assert world.export() == before and world.rng_ops.getstate() == rng
    assert all(not (set(path) & (HIDDEN - {"health"})) for path in walk(screen))
    json.dumps(screen)


def test_market_inventory_and_public_config_views():
    world = World(2)
    screen = build(world)
    assert screen["market"]["spot_rate_index"] % 10 == 0
    assert screen["suppliers"]["S-SOC"]["quoted_lead_days"]["SOC"] == 60
    assert screen["suppliers"]["S-SOC"]["components"] == ["SOC"]
    assert screen["customers"]["C-BIGBOX"]["dc"] == "DC-DE"
    assert screen["inventory"]["DC-DE"]["EB-STD"]["on_hand"] == world.stock["DC-DE"]["EB-STD"]
    assert screen["suppliers"]["S-SOC"]["scorecard"] is None


def test_dc_cover_uses_regional_demand_and_inbound_queue_survives_record_close():
    world = World(2)
    screen = build(world)
    weekly = screen["forecast"]["EB-STD"][0]
    expected = round(world.stock["DC-PL"]["EB-STD"] / (weekly * .20 / 5), 1)
    assert screen["inventory"]["DC-PL"]["EB-STD"]["days_of_cover"] == expected
    world.dc_inbound_queue["DC-PL"].append(("EB-STD", 321))
    transfer = world.records.new("transfer", world.day, "delivered", src="DC-NL", dst="DC-PL",
                                 mode="rail", lines={"EB-STD": 321}, pallets=1, eta_day=world.day, cost=90)
    assert transfer not in world.records.open("transfer")
    assert build(world)["inventory"]["DC-PL"]["EB-STD"]["in_transit_to"] == 321


def test_sampled_future_dates_and_internal_quality_do_not_leak():
    world = World(4)
    po = world.records.all("po")[0]
    assert po.state == "in_production" and po.data["ship_day"] is not None
    view = record_view(po)
    assert "ship_day" not in view["data"] and "actual_ship_day" not in view["data"]
    assert "confirm_day" not in view["data"] and "invoice_day" not in view["data"]
    wo = world.records.new("work_order", world.day, "released", sku="EB-STD", qty=1,
                           produced=0, started_day=world.day, defect_rate=987654)
    lot = world.records.new("lot", world.day, "sampling", po_id=po.id, supplier="S-BAT",
                            component="BAT", qty=10, defects_true=9, dppm=876543)
    assert "defect_rate" not in record_view(wo)["data"]
    assert "defects_true" not in record_view(lot)["data"] and "dppm" not in record_view(lot)["data"]


def test_audit_result_is_visible_only_after_completion():
    world = World(6)
    world.cond.supplier_health["S-SOC"] = "strained"
    world.apply({"type": "request_audit", "supplier": "S-SOC"})
    pending = build(world)
    assert pending["suppliers"]["S-SOC"]["audit"] is None
    assert all("health" not in r["data"] for r in pending["records"]["audit"])
    for _ in range(4): world.end_day()
    screen = build(world)
    assert screen["suppliers"]["S-SOC"]["audit"]["health"] == "strained"
