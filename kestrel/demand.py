"""True demand, promotions, lifecycle and the (noisy) forecast the planner sees (SPEC §6.5)."""
import math, random
from datetime import date
from . import calendar as cal
from .network import CUSTOMERS, PRODUCTS

BASE = {"EB-STD": 900, "EB-PRO": 350, "SPK-1": 200}
PROMO_UPLIFT, PROMO_DISCOUNT, PROMO_NOTICE = 1.35, 0.20, 42
NOISE_SD = 0.35
REFRESH = cal.to_day(date(2026, 9, 1))


class DemandModel:
    def __init__(self, seed: int):
        self.seed = seed
        r = random.Random(seed * 7919 + 1)
        self.markdown: dict[str, float] = {}
        self.promos = []
        for cid in CUSTOMERS:
            for _ in range(r.randint(2, 4)):
                start = r.randint(PROMO_NOTICE + 7, cal.N_DAYS - 15)
                self.promos.append({"customer": cid, "sku": r.choice(list(PRODUCTS)), "start_day": start, "end_day": start + 6,
                                    "announced_day": start - PROMO_NOTICE, "discount": PROMO_DISCOUNT})
        self.promos.sort(key=lambda p: p["start_day"])
        self._daily_cache: dict = {}

    def lifecycle(self, day, sku):
        if sku != "EB-PRO":
            return 1.0
        if day < REFRESH:
            return 1.0
        return max(0.4, 1.0 - 0.6 * (day - REFRESH) / 56)

    def promo_factor(self, day, sku, customer, as_of: int | None = None):
        promos = self.promos if as_of is None else [p for p in self.promos if p["announced_day"] <= as_of]
        return PROMO_UPLIFT if any(p["customer"] == customer and p["sku"] == sku and p["start_day"] <= day <= p["end_day"] for p in promos) else 1.0

    def expected_customer(self, day, sku, customer, as_of: int | None = None):
        return (BASE[sku] * CUSTOMERS[customer].share * cal.season_factor(sku, day)
                * self.promo_factor(day, sku, customer, as_of=as_of) * self.lifecycle(day, sku)
                * self.markdown.get(sku, 1.0))

    def expected(self, day, sku, as_of: int | None = None):
        return sum(self.expected_customer(day, sku, c, as_of=as_of) for c in CUSTOMERS)

    def demand(self, day, sku, customer) -> int:
        key = (day, sku, customer)
        if key not in self._daily_cache:
            if not cal.is_working("customer", day):
                self._daily_cache[key] = 0
            else:
                mu = self.expected_customer(day, sku, customer)
                rng = random.Random(f"{self.seed}:{day}:{sku}:{customer}")
                self._daily_cache[key] = max(0, round(mu * math.exp(rng.gauss(-NOISE_SD**2 / 2, NOISE_SD))))
        return self._daily_cache[key]

    def order_qty(self, day, sku, customer) -> int:
        wd = CUSTOMERS[customer].order_weekday
        if wd is None:
            return self.demand(day, sku, customer)
        if cal.weekday(day) != wd:
            return 0
        return sum(self.demand(d, sku, customer) for d in range(day, day + 7))

    def announced_promos(self, day):
        return [p for p in self.promos if p["announced_day"] <= day]

    def forecast_baseline(self, day, sku) -> list:
        """Noise-free forecast baseline: 13 weekly totals, promos filtered to those announced by `day`."""
        weeks = []
        for w in range(13):
            start = day + 7 * w
            true = sum(self.expected(d, sku, as_of=day) for d in range(start, start + 7) if cal.is_working("customer", d))
            weeks.append(true)
        return weeks

    def forecast(self, day) -> dict:
        out = {}
        for sku in PRODUCTS:
            baseline = self.forecast_baseline(day, sku)
            weeks = []
            for w, true in enumerate(baseline):
                sd = 0.30 + 0.025 * w
                rng = random.Random(f"{self.seed}:fc:{day}:{sku}:{w}")
                err = rng.gauss(0, sd)
                weeks.append(round(true * max(0.1, 1 + err), 1))
            out[sku] = weeks
        return out
