"""Hidden conditions (SPEC §6.1-6.4). Advance once per day from rng_cond in a fixed order; never read planner state.
Cascade order: lane -> rates -> port -> supplier lead times."""
import random
from . import calendar as cal
from .network import SUPPLIERS

HEALTH_ORDER = ("S-BAT", "S-SOC", "S-BRK", "S-DRV", "S-CASE")
OTIF = {"healthy": 0.95, "strained": 0.85, "distressed": 0.65, "insolvent": 0.0}
SHORT = {"healthy": 0.0, "strained": 0.10, "distressed": 0.35, "insolvent": 1.0}
DPPM = {"healthy": 800, "strained": 2500, "distressed": 8000, "insolvent": 8000}
LAG = {"healthy": 0, "strained": 2, "distressed": 5, "insolvent": 99}
SPOT = {"normal": 1800.0, "elevated": 3200.0, "crisis": 5000.0}
PORT_CAP = 40

class Conditions:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.lane, self.lane_age, self.blocked_until, self.blocked_from = "open", 0, -1, "open"
        self.port_q, self.strike_until = 0.0, -1
        self.rate_regime, self.spot = "normal", SPOT["normal"]
        self.supplier_health = {s: "healthy" for s in HEALTH_ORDER}
        self.alloc, self.alloc_age = "normal", 0
        self.pending_news: list = []

    # -- daily advance -------------------------------------------------------
    def advance(self, day: int) -> list:
        r = self.rng
        # lane
        if self.lane == "open":
            u = r.random()
            if u < 0.004: self._force_lane("diverted", day)
            elif u < 0.005: self._force_lane("blocked", day)
        elif self.lane == "diverted":
            self.lane_age += 1
            if r.random() < 1 / 120: self._force_lane("open", day)
        elif self.lane == "blocked" and day >= self.blocked_until:
            self._force_lane("open", day); self.port_q += 200   # the queue of delayed ships lands together
        # port strike
        if self.strike_until < day and r.random() < 0.01:
            self.strike_until = day + 8
            self._news(day, day, "Port of Rotterdam", "Dockworker strike begins", "Terminal capacity reduced to 30% for eight days.", "port")
        # rate regime (diversion forces crisis)
        if self.lane == "diverted": self.rate_regime = "crisis"
        elif self.rate_regime == "crisis": self.rate_regime = "elevated"
        elif self.rate_regime == "normal" and r.random() < 0.01: self.rate_regime = "elevated"
        elif self.rate_regime == "elevated" and r.random() < 0.03: self.rate_regime = "normal"
        base = SPOT[self.rate_regime] * (1.2 if cal.freight_tight(day) else 1.0)
        self.spot = base * max(0.5, r.gauss(1.0, 0.08))
        # port queue decay
        self.port_q *= 0.9
        # supplier health
        for s in HEALTH_ORDER:
            h = self.supplier_health[s]; u = r.random()
            if h == "healthy" and u < 0.003: self._set_health(s, "strained", day)
            elif h == "strained":
                if u < 0.02: self._set_health(s, "healthy", day)
                elif u < 0.025: self._set_health(s, "distressed", day)
            elif h == "distressed" and u < 0.003: self._set_health(s, "insolvent", day)
        # allocation
        if self.alloc == "normal" and r.random() < 0.003:
            self.alloc, self.alloc_age = "allocated", 0
            self._news(day, day + 3, "S-SOC", "Allocation notice", "Audio SoC supply is on allocation; confirmations will be prorated to trailing volume.", "supplier")
        elif self.alloc == "allocated":
            self.alloc_age += 1
            if r.random() < 1 / 150: self.alloc = "normal"; self._news(day, day + 3, "S-SOC", "Allocation lifted", "Normal confirmations resume.", "supplier")
        due = [n for p, n in self.pending_news if p <= day]
        self.pending_news = [(p, n) for p, n in self.pending_news if p > day]
        return due

    def _force_lane(self, state, day):
        prev, self.lane, self.lane_age = self.lane, state, 0
        if state == "blocked": self.blocked_until = day + self.rng.randint(4, 8)
        if state == "diverted":
            self.rate_regime = "crisis"; self.spot = SPOT["crisis"]
            self._news(day, day + self.rng.randint(2, 10), "Carrier alliance notice", "Asia-Europe services rerouted via the Cape of Good Hope",
                       "Transit times extend by 10-14 days on the Cape of Good Hope route; war-risk surcharge applies.", "lane")
        elif state == "blocked":
            self._news(day, day, "Suez Canal Authority", "Canal transit suspended", "A grounded vessel blocks the canal; convoys halted.", "lane")
        elif state == "open" and prev != "open":
            self._news(day, day + 2, "Carrier alliance notice", "Suez routing resumes", "Services return to the canal; transit normalises over coming sailings.", "lane")

    def _set_health(self, s, h, day):
        self.supplier_health[s] = h
        if h == "insolvent":
            self._news(day, day + 1, s, f"{s} enters insolvency", "Open orders will not ship; administrators appointed.", "supplier")

    def _news(self, day, publish_day, source, title, body, kind):
        self.pending_news.append((publish_day, {"day": publish_day, "source": source, "title": title, "body": body, "kind": kind}))

    # -- derived (read by record logic; rng_ops supplied by caller) ----------
    def transit_days(self, mode, route, rng_ops, day) -> int:
        if mode == "air": return max(5, round(rng_ops.gauss(6, 1.0)))
        if mode == "sea_air": return max(15, round(rng_ops.gauss(20, 1.5)))
        mean = 42 if (route == "cape" or self.lane == "diverted") else 30
        d = rng_ops.gauss(mean, 1.5)
        if rng_ops.random() > 0.65: d += rng_ops.uniform(3, 10)          # schedule reliability 65%
        if cal.golden_week_backlog(day): d += 14
        return max(20, round(d))
    def port_capacity(self, day) -> int: return int(PORT_CAP * 0.3) if self.strike_until >= day else PORT_CAP
    def add_arrivals(self, n: int, day: int = None):
        cap = self.port_capacity(day) if day is not None else PORT_CAP
        self.port_q += max(0, n - cap)
    def berth_wait_days(self) -> int: return min(10, int(self.port_q / PORT_CAP))
    def spot_rate(self) -> float: return self.spot
    def otif(self, s): return OTIF[self.supplier_health[s]]
    def short_ship_prob(self, s): return SHORT[self.supplier_health[s]]
    def dppm(self, s): return DPPM[self.supplier_health[s]]
    def confirm_lag(self, s): return LAG[self.supplier_health[s]]
    def quoted_lead(self, s, c):
        base = SUPPLIERS[s].lead_days[c]
        return int(base * 1.5) if (self.alloc == "allocated" and s == "S-SOC") else base
    def to_dict(self):
        return {"lane": self.lane, "lane_age": self.lane_age, "port_q": round(self.port_q, 3), "strike_until": self.strike_until,
                "rate_regime": self.rate_regime, "spot": round(self.spot, 2), "supplier_health": dict(self.supplier_health), "alloc": self.alloc}
