import inspect

from kestrel import planner
from kestrel.world import World


def test_planner_never_touches_hidden_state():
    src = inspect.getsource(planner)
    assert "cond" not in src and "supplier_health" not in src


def test_planner_keeps_dcs_stocked_for_60_days():
    world = World(1)
    reports = planner.run(world, 60)
    assert len(reports) == 60
    screen = world.screens()
    for dc in ("DC-DE", "DC-PL"):
        assert screen["inventory"][dc]["EB-STD"]["on_hand"] > 0
    assert world.records.all("po") and world.records.all("booking") and world.records.all("work_order")


def test_plan_accounts_for_stock_used_earlier_in_batch():
    world = World(4)
    for sku in planner.PRODUCTS:
        world.stock["DC-NL"][sku] = planner.PRODUCTS[sku].per_pallet
        world.stock["DC-DE"][sku] = 0
        world.stock["DC-PL"][sku] = 0
    actions = planner.plan_day(world)
    moved = {}
    for action in actions:
        if action["type"] == "create_transfer":
            for sku, qty in action["lines"].items():
                moved[sku] = moved.get(sku, 0) + qty
    assert all(qty <= planner.PRODUCTS[sku].per_pallet for sku, qty in moved.items())


def test_run_retains_actions_and_real_results():
    world = World(2)
    report = planner.run(world, 1)[0]
    assert len(report["actions"]) == len(report["results"])
    assert all(set(result) >= {"ok", "reason", "id"} for result in report["results"])
    assert isinstance(planner.note(world), str) and planner.note(world)


def test_planner_does_not_repeat_a_disputed_invoice():
    world = World(3)
    invoice = world.records.new("invoice_in", 0, "blocked", amount=106, expected=100,
                                po_id=None, supplier="S-SOC", due_day=30)
    world.exception("invoice", invoice.id, "mismatch")
    first = planner.plan_day(world)
    assert {"type": "dispute_invoice", "invoice_id": invoice.id} in first
    world.apply({"type": "dispute_invoice", "invoice_id": invoice.id})
    assert not any(a.get("invoice_id") == invoice.id for a in planner.plan_day(world))
