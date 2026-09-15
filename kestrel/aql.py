"""ISO 2859-1 (AQL 1.0%) sampling tables and plan lookup, split out of procurement.py to keep
that module under its line-count cap (task-8 fix round 1)."""

AQL_SAMPLE = [(1200, 80), (3200, 125), (10000, 200), (35000, 315), (150000, 500)]
ACCEPT = {80: 2, 125: 3, 200: 5, 315: 7, 500: 10}
LEVEL_SHIFT = {"I": -1, "II": 0, "III": 1}


def sample_plan(lot_qty: int, level: str) -> tuple[int, int]:
    """Sample size and AQL-1.0% acceptance number for a lot of this size at this level."""
    idx = next((i for i, (ub, _) in enumerate(AQL_SAMPLE) if lot_qty <= ub), len(AQL_SAMPLE) - 1)
    idx = min(len(AQL_SAMPLE) - 1, max(0, idx + LEVEL_SHIFT[level]))
    table_n = AQL_SAMPLE[idx][1]
    return min(lot_qty, table_n), ACCEPT[table_n]
