"""Calendar: real 2026 dates, working days, and every date-anchored effect (SPEC §4)."""
from datetime import date, timedelta

START = date(2026, 1, 5)
END = date(2026, 12, 31)
N_DAYS = (END - START).days + 1

def to_date(day: int) -> date: return START + timedelta(days=day)
def to_day(d: date) -> int: return (d - START).days
def weekday(day: int) -> int: return to_date(day).weekday()

def is_working(kind: str, day: int) -> bool:
    wd = weekday(day)
    return {"dc": wd < 5, "customer": wd < 5, "plant": wd < 6, "sea": True}[kind]

def _d(m, d): return to_day(date(2026, m, d))

CNY_DOWN_START, CNY_START, CNY_END, CNY_UP_END = _d(1, 25), _d(2, 15), _d(2, 23), _d(3, 23)
GW_START, GW_END = _d(10, 1), _d(10, 7)

def china_capacity_factor(day: int) -> float:
    """Supplier and plant capacity multiplier: linear ramp-down over three weeks, zero
    during the holiday, linear ramp-up over four weeks (SPEC §4)."""
    if CNY_DOWN_START <= day < CNY_START:
        return 1.0 - (day - CNY_DOWN_START) / (CNY_START - CNY_DOWN_START)
    if CNY_START <= day <= CNY_END:
        return 0.0
    if CNY_END < day <= CNY_UP_END:
        return (day - CNY_END) / (CNY_UP_END - CNY_END)
    if GW_START - 7 <= day < GW_START:
        return 1.0 - 0.5 * (day - (GW_START - 7)) / 7
    if GW_START <= day <= GW_END:
        return 0.0
    if GW_END < day <= GW_END + 7:
        return 0.5 + 0.5 * (day - GW_END) / 7
    return 1.0

def season_factor(sku: str, day: int) -> float:
    if _d(11, 23) <= day <= _d(11, 29):
        return 3.5 if sku == "EB-PRO" else 3.0
    if _d(12, 1) <= day <= _d(12, 23):
        return 1.6
    if sku == "EB-STD" and _d(8, 15) <= day <= _d(9, 15):
        return 1.4
    if sku == "SPK-1" and _d(6, 1) <= day <= _d(8, 31):
        return 1.5
    return 1.0

def freight_tight(day: int) -> bool: return CNY_DOWN_START <= day <= _d(3, 15)
def pss_in_season(day: int) -> bool: return _d(8, 1) <= day <= _d(11, 30)
def contract_window(day: int) -> bool: return _d(5, 1) <= day <= _d(5, 15)
def golden_week_backlog(day: int) -> bool: return GW_START <= day <= GW_END + 14

EVENTS = [
    {"name": "Chinese New Year", "start_day": CNY_DOWN_START, "end_day": CNY_UP_END, "note": "holiday 15-23 Feb; capacity ramps down from 25 Jan and back up to 23 Mar"},
    {"name": "Freight contract season", "start_day": _d(5, 1), "end_day": _d(5, 15), "note": "12-month contract rate can be signed"},
    {"name": "Summer", "start_day": _d(6, 1), "end_day": _d(8, 31), "note": "speaker demand x1.5"},
    {"name": "Back-to-school", "start_day": _d(8, 15), "end_day": _d(9, 15), "note": "standard earbuds x1.4"},
    {"name": "Golden Week", "start_day": GW_START, "end_day": GW_END, "note": "China closed 1-7 Oct; transit backlog two weeks"},
    {"name": "Black Friday", "start_day": _d(11, 23), "end_day": _d(11, 29), "note": "demand x3 (pro x3.5)"},
    {"name": "Christmas", "start_day": _d(12, 1), "end_day": _d(12, 23), "note": "demand x1.6"},
]
