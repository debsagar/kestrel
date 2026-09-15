import time

from kestrel import checks, fulfilment, planner
from kestrel.world import World


def test_full_year_three_seeds():
    for seed in (1, 2, 3):
        started = time.perf_counter()
        world = World(seed)
        planner.run(world, 361)
        checks.verify(world)
        assert world.done and time.perf_counter() - started < 30
        assert world.ledger.total("revenue") > 0
        assert min(fulfilment.otif(world, customer)
                   for customer in ("C-BIGBOX", "C-MARKET", "C-PLCHAIN")) > 0.8
