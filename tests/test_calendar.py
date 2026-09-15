from datetime import date
from kestrel import calendar as cal

def test_start_and_length():
    assert cal.START == date(2026, 1, 5) and cal.START.weekday() == 0
    assert cal.to_date(cal.N_DAYS - 1) == date(2026, 12, 31)
    assert cal.to_day(date(2026, 2, 15)) == 41

def test_working_days():
    sat = cal.to_day(date(2026, 1, 10))
    assert not cal.is_working("dc", sat) and cal.is_working("plant", sat)
    assert not cal.is_working("plant", sat + 1) and cal.is_working("sea", sat + 1)
    assert not cal.is_working("customer", sat)

def test_cny_ramp():
    assert cal.china_capacity_factor(cal.to_day(date(2026, 1, 20))) == 1.0
    assert cal.china_capacity_factor(cal.to_day(date(2026, 2, 18))) == 0.0
    mid = cal.china_capacity_factor(cal.to_day(date(2026, 2, 5)))
    assert 0.0 < mid < 1.0
    assert cal.china_capacity_factor(cal.to_day(date(2026, 3, 24))) == 1.0
    assert cal.china_capacity_factor(cal.to_day(date(2026, 10, 3))) == 0.0

def test_season():
    assert cal.season_factor("EB-STD", cal.to_day(date(2026, 8, 20))) == 1.4
    assert cal.season_factor("EB-PRO", cal.to_day(date(2026, 11, 25))) == 3.5
    assert cal.season_factor("SPK-1", cal.to_day(date(2026, 7, 1))) == 1.5
    assert cal.season_factor("SPK-1", cal.to_day(date(2026, 12, 10))) == 1.6
    assert cal.season_factor("EB-STD", cal.to_day(date(2026, 4, 1))) == 1.0

def test_freight_flags():
    assert cal.freight_tight(cal.to_day(date(2026, 2, 1)))
    assert not cal.freight_tight(cal.to_day(date(2026, 6, 1)))
    assert cal.pss_in_season(cal.to_day(date(2026, 9, 1))) and not cal.pss_in_season(cal.to_day(date(2026, 3, 1)))
    assert cal.contract_window(cal.to_day(date(2026, 5, 10))) and not cal.contract_window(cal.to_day(date(2026, 5, 20)))

def test_events_listed():
    names = {e["name"] for e in cal.EVENTS}
    assert {"Chinese New Year", "Golden Week", "Black Friday", "Christmas", "Back-to-school", "Freight contract season"} <= names
