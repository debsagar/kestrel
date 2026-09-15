"""Cash ledger and P&L (SPEC §9).

Operating services are paid when posted.  Product cost, write-offs, and holding
charges remain standard-cost/non-cash accounting entries; customer and supplier
documents keep their explicit settlement timing.
"""
HOLDING_RATE = 0.25
CASH = {"deposit", "balance", "customer_receipt", "supplier_payment", "credit", "operating_payment"}
PAID_OPERATING_EXPENSES = {"freight", "surcharges", "demurrage", "inter_dc", "expedite",
                           "returns", "inspection", "audits"}
PNL_GROUPS = {"revenue": ["revenue"], "cogs": ["cogs_components", "cogs_assembly"], "freight": ["freight"], "surcharges": ["surcharges"],
              "demurrage": ["demurrage"], "inter_dc": ["inter_dc"], "expedite": ["expedite"], "holding": ["holding"], "chargebacks": ["chargebacks"],
              "returns": ["returns"], "writeoffs": ["writeoffs"], "inspection": ["inspection"], "audits": ["audits"], "markdown": ["markdown"]}
ALL_CATEGORIES = CASH | {c for cats in PNL_GROUPS.values() for c in cats}


class Ledger:
    def __init__(self, opening_cash: float):
        self.opening_cash = opening_cash; self.cash = opening_cash; self.lines = []

    def post(self, day, category, amount, ref=""):
        if category not in ALL_CATEGORIES:
            raise ValueError(f"unknown ledger category: {category!r}")
        self.lines.append((day, category, float(amount), ref))
        if category in CASH: self.cash += amount
        elif category in PAID_OPERATING_EXPENSES and amount:
            # Keep the accrual visible in P&L and record its one cash settlement.
            self.lines.append((day, "operating_payment", float(amount), ref))
            self.cash += amount

    def total(self, category, day_from=0, day_to=None):
        return sum(a for d, c, a, _ in self.lines if c == category and d >= day_from and (day_to is None or d <= day_to))

    def holding_charge(self, day, inventory_value):
        self.post(day, "holding", -inventory_value * HOLDING_RATE / 365, "daily holding")

    def pnl(self, day, day_from=0):
        """P&L over accrual categories for [day_from, day]; day_from is an optional windowing start (default 0 = since inception)."""
        out = {g: sum(self.total(c, day_from, day) for c in cats) for g, cats in PNL_GROUPS.items()}
        out["operating_result"] = sum(out.values()); return out

    @staticmethod
    def working_capital(day, receivables, payables, inventory_value, revenue_90d, cogs_90d):
        dso = receivables / revenue_90d * 90 if revenue_90d else 0.0
        dpo = payables / cogs_90d * 90 if cogs_90d else 0.0
        dio = inventory_value / cogs_90d * 90 if cogs_90d else 0.0
        return {"dio": dio, "dso": dso, "dpo": dpo, "ccc": dio + dso - dpo}
