import random
from datetime import date

from kestrel import calendar as cal
from kestrel.conditions import Conditions


def run(c, days):
    news = []
    for d in range(days): news += c.advance(d)
    return news

def test_seed_determinism_independent_of_ops_rng():
    a, b = Conditions(3), Conditions(3)
    run(a, 200); run(b, 200)
    assert a.to_dict() == b.to_dict()

def test_diversion_forces_crisis_and_news_lags():
    c = Conditions(1); c.lane = "open"; c.rng = random.Random(0)
    c._force_lane("diverted", day=10)
    assert c.rate_regime == "crisis" and c.spot_rate() > 4000
    published = [n for n in c.advance(10)] + [n for n in c.advance(11)]
    assert not any(n["kind"] == "lane" for n in published)      # lag is 2-10 days
    late = sum((c.advance(d) for d in range(12, 25)), [])
    assert any(n["kind"] == "lane" and "Cape" in n["body"] for n in late)

def test_transit_by_lane():
    c = Conditions(2); ops = random.Random(0)
    c.lane = "open"; open_days = [c.transit_days("ocean", "suez", ops, 100) for _ in range(200)]
    c.lane = "diverted"; div_days = [c.transit_days("ocean", "suez", ops, 100) for _ in range(200)]
    assert 28 <= sum(open_days)/200 <= 36 and sum(div_days)/200 > 40
    assert 5 <= c.transit_days("air", None, ops, 100) <= 9

def test_golden_week_backlog_adds_transit_days():
    c = Conditions(2); ops = random.Random(0)
    c.lane = "open"
    gw_day = cal.to_day(date(2026, 10, 3))
    gw_days = [c.transit_days("ocean", "suez", ops, gw_day) for _ in range(200)]
    normal_days = [c.transit_days("ocean", "suez", ops, 100) for _ in range(200)]
    assert sum(gw_days)/200 >= sum(normal_days)/200 + 14

def test_port_queue_decays_and_caps():
    c = Conditions(4); c.add_arrivals(400)
    assert c.berth_wait_days() == 9
    c.port_q = 1000; assert c.berth_wait_days() == 10
    c.strike_until = -1; c.lane = "open"; c.rng = random.Random(0)
    c.advance(0); assert c.port_q < 1000

def test_port_capacity_reduced_during_strike():
    c = Conditions(4)
    c.strike_until = 20
    assert c.port_capacity(10) == int(40 * 0.3)
    assert c.port_capacity(20) == int(40 * 0.3)
    assert c.port_capacity(21) == 40

def test_supplier_health_effects():
    c = Conditions(5)
    c.supplier_health["S-SOC"] = "distressed"
    assert c.otif("S-SOC") == 0.65 and c.dppm("S-SOC") == 8000 and c.confirm_lag("S-SOC") == 5
    c.supplier_health["S-SOC"] = "insolvent"; assert c.otif("S-SOC") == 0.0
    c.alloc = "allocated"; assert c.quoted_lead("S-SOC", "SOC") == 90 and c.quoted_lead("S-BAT", "BAT") == 35
