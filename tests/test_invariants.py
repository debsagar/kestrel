import random

from kestrel import checks, planner
from kestrel.world import World


def test_invariants_hold_every_day_for_90_days_under_the_planner():
    world = World(11)
    for _ in range(90):
        for action in planner.plan_day(world):
            world.apply(action)
        world.end_day()
        checks.verify(world)


def test_invariants_hold_under_random_actions():
    world, rng = World(12), random.Random(0)
    for _ in range(60):
        for _ in range(3):
            action = rng.choice([
                {"type": "release_work_order", "sku": "EB-STD", "qty": rng.randint(1, 3000)},
                {"type": "create_transfer", "src": "DC-NL", "dst": "DC-PL", "mode": "rail",
                 "lines": {"SPK-1": rng.randint(1, 500)}},
                {"type": "book_container", "mode": "air", "route": None,
                 "lines": {"EB-STD": rng.randint(1, 2000)}, "rate_type": "spot"},
                {"type": "create_po", "supplier": "S-BAT", "component": "BAT", "qty": 5000,
                 "requested_day": world.day + 40, "incoterm": "FOB"},
            ])
            world.apply(action)
        world.end_day()
        checks.verify(world)


def test_inventory_value_includes_non_stock_positions():
    world = World(3)
    base = world.inventory_value()
    assert world.apply({"type": "release_work_order", "sku": "EB-STD", "qty": 10})["ok"]
    # Moving standard-cost components into WIP does not change inventory value.
    assert world.inventory_value() == base
