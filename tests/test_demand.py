from kestrel.demand import DemandModel, BASE
from kestrel import calendar as cal
from datetime import date

def test_expected_uses_season_and_lifecycle():
    m = DemandModel(1)
    assert m.expected(cal.to_day(date(2026, 4, 1)), "EB-STD") == BASE["EB-STD"]
    assert m.expected(cal.to_day(date(2026, 11, 25)), "EB-PRO") >= 350 * 3.5 * 0.4
    assert m.lifecycle(cal.to_day(date(2026, 10, 27)), "EB-PRO") == 0.4

def test_promos_announced_six_weeks_ahead():
    m = DemandModel(2)
    assert all(p["start_day"] - p["announced_day"] == 42 for p in m.promos)
    assert all(2 <= sum(1 for p in m.promos if p["customer"] == c) <= 4 for c in ("C-BIGBOX","C-MARKET","C-PLCHAIN","C-WEB"))
    p = m.promos[0]
    assert m.announced_promos(p["announced_day"] - 1).count(p) == 0 and p in m.announced_promos(p["announced_day"])

def test_demand_is_deterministic_and_zero_on_weekends():
    a, b = DemandModel(3), DemandModel(3)
    days = range(0, 60)
    assert [a.demand(d, "EB-STD", "C-WEB") for d in days] == [b.demand(d, "EB-STD", "C-WEB") for d in days]
    assert a.demand(cal.to_day(date(2026, 1, 10)), "EB-STD", "C-WEB") == 0
    mean = sum(a.demand(d, "EB-STD", "C-WEB") for d in range(0, 250) if cal.is_working("customer", d)) / sum(1 for d in range(0, 250) if cal.is_working("customer", d))
    assert 0.7 * 900 * 0.15 < mean < 1.5 * 900 * 0.15

def test_forecast_shape_and_error_growth():
    m = DemandModel(4); f = m.forecast(10)
    assert set(f) == {"EB-STD","EB-PRO","SPK-1"} and len(f["EB-STD"]) == 13
    assert m.forecast(10) == f
    errs = [abs(m.forecast(d)["EB-STD"][w] / (m.expected(d + 7*w + 3, "EB-STD") * 5) - 1) for d in range(0, 100, 5) for w in (0, 12)]
    assert sum(errs[1::2]) > sum(errs[0::2])    # week-13 error larger than week-1 error on average

def test_forecast_excludes_unannounced_promos():
    m = DemandModel(4); p = m.promos[0]
    days = range(p["start_day"], p["end_day"] + 1)
    before = sum(m.expected(d, p["sku"], as_of=p["announced_day"] - 1) for d in days)
    at = sum(m.expected(d, p["sku"], as_of=p["announced_day"]) for d in days)
    true = sum(m.expected(d, p["sku"]) for d in days)
    assert before < at == true

    # forecast_baseline must actually pass the as_of cutoff through, not just expected() directly:
    # push the promo's announcement far into the future and confirm the baseline for a week
    # overlapping the (now unannounced) promo matches an as_of-gated expected() sum, and is
    # below the ungated (true) sum.
    saved_announced = p["announced_day"]
    p["announced_day"] = 10**6
    try:
        day = p["start_day"] - 3
        week0 = m.forecast_baseline(day, p["sku"])[0]
        gated = sum(m.expected(d, p["sku"], as_of=day) for d in range(day, day + 7) if cal.is_working("customer", d))
        ungated = sum(m.expected(d, p["sku"]) for d in range(day, day + 7) if cal.is_working("customer", d))
        assert week0 == gated < ungated
    finally:
        p["announced_day"] = saved_announced

def test_weekly_batching():
    m = DemandModel(5)
    mon = cal.to_day(date(2026, 3, 2)); tue = mon + 1
    assert m.order_qty(tue, "EB-STD", "C-BIGBOX") == 0 and m.order_qty(mon, "EB-STD", "C-BIGBOX") > 0
    assert m.order_qty(tue, "EB-STD", "C-MARKET") == m.demand(tue, "EB-STD", "C-MARKET")
