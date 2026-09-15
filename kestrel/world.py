"""The World: owns records, stock, ledger, conditions, demand; runs the day loop (SPEC §7-§9)."""
import random
from . import calendar as cal
from .conditions import Conditions
from .demand import DemandModel
from .finance import Ledger
from .network import COMPONENTS, CUSTOMERS, DCS, NODES, PRODUCTS, SUPPLIERS, component_cost, price_for, PRIMARY_SUPPLIER
from .records import IllegalTransition, RecordStore

OPENING_CASH = 2_500_000.0


class _Noop:
    ACTIONS: dict = {}
    @staticmethod
    def advance(world): pass
    @staticmethod
    def seed_opening(world): pass


def _modules():
    mods = []
    for name in ("procurement", "logistics", "plant", "distribution", "fulfilment"):
        try: mods.append(__import__(f"kestrel.{name}", fromlist=[name]))
        except ImportError as e:
            if e.name != f"kestrel.{name}": raise
            mods.append(_Noop)
    return mods


class World:
    def __init__(self, seed: int):
        self.seed, self.day, self.done = seed, 0, False
        self.records, self.ledger = RecordStore(), Ledger(OPENING_CASH)
        self.cond, self.demand = Conditions(seed), DemandModel(seed)
        self.rng_ops = random.Random(seed * 104729 + 7)
        self.stock = {n: {} for n in NODES}
        self.allocated = {dc: {s: 0 for s in PRODUCTS} for dc in DCS}
        self.news, self.exceptions, self.day_log = [], [], []
        self.allocation_policy = {"mode": "priority", "order": ["C-BIGBOX", "C-MARKET", "C-PLCHAIN", "C-WEB"]}
        self.inspection_level = {s: "II" for s in SUPPLIERS}
        self.contract = None
        self.trailing_volume = {s: [] for s in SUPPLIERS}
        self.qualified = {s: SUPPLIERS[s].qualified for s in SUPPLIERS}

        # controller ruling: fields later tasks (8-13) introduce, declared up front.
        self.dc_inbound_queue = {dc: [] for dc in DCS}
        self.dc_inbound_capacity = {dc: 30 for dc in DCS}
        self.blank_sailings: list = []
        self.flows = {k: 0 for k in ("produced", "shipped_customers", "restocked", "written_off",
                                      "consumed_components", "received_components", "sorted_out", "returned_lots")}
        self.scorecards = {}
        self.component_dppm = {c: 800 for c in COMPONENTS}
        self.last_sku = None
        self.markdown = {}

        self.modules = _modules()
        self.actions = {k: (m, f) for m in self.modules for k, f in m.ACTIONS.items()}
        self._open_position()
        for m in self.modules: m.seed_opening(self)
        self.opening_physical = self._physical_position()

    def _open_position(self):
        for dc in DCS:
            share = sum(c.share for c in CUSTOMERS.values() if c.dc == dc) or 0.0
            for sku in PRODUCTS:
                self.stock[dc][sku] = int(self.demand.expected(0, sku) * (share if dc != "DC-NL" else 0.3) * 20)
        for comp in COMPONENTS:
            self.stock["PLANT"][comp] = int(sum(self.demand.expected(0, s) * p.bom.get(comp, 0) for s, p in PRODUCTS.items()) * 30)
        for sku in PRODUCTS: self.stock["PLANT"][sku] = 0

    # -- stock ---------------------------------------------------------------
    def add_stock(self, node, item, qty): self.stock[node][item] = self.stock[node].get(item, 0) + int(qty)
    def take_stock(self, node, item, qty):
        have = self.stock[node].get(item, 0)
        if qty > have: raise ValueError(f"{node} has {have} {item}, need {qty}")
        self.stock[node][item] = have - int(qty)
    def _physical_position(self):
        """Per-item company-owned units at reset, including seeded transit."""
        out = {item: sum(items.get(item, 0) for items in self.stock.values())
               for item in COMPONENTS + tuple(PRODUCTS)}
        for rec in self.records.all("booking"):
            if rec.state != "cancelled":
                for sku, qty in rec.data["lines"].items(): out[sku] += qty
        return out

    def inventory_value(self) -> float:
        """Standard-cost value of on-hand, WIP, quarantine, and owned transit."""
        component_standard = {c: price_for(PRIMARY_SUPPLIER[c], c, SUPPLIERS[PRIMARY_SUPPLIER[c]].moq[c])
                              for c in COMPONENTS}
        product_standard = {s: component_cost(s) + PRODUCTS[s].assembly_cost for s in PRODUCTS}
        v = 0.0
        for node, items in self.stock.items():
            for item, q in items.items():
                v += q * (component_standard[item] if item in COMPONENTS else product_standard[item])
        for po in self.records.all("po"):
            if po.state == "shipped": v += (po.data.get("shipped_qty") or 0) * component_standard[po.data["component"]]
        for lot in self.records.all("lot"):
            v += lot.data.get("quarantined_qty", 0) * component_standard[lot.data["component"]]
        for wo in self.records.open("work_order"):
            remaining = wo.data["qty"] - wo.data["produced"]
            v += remaining * component_cost(wo.data["sku"])
        for rec in self.records.all("booking"):
            if rec.state != "cancelled" and rec.state != "delivered":
                v += sum(q * product_standard[s] for s, q in rec.data["lines"].items())
        for rec in self.records.open("transfer"):
            v += sum(q * product_standard[s] for s, q in rec.data["lines"].items())
        for queue in self.dc_inbound_queue.values():
            v += sum(q * product_standard[s] for s, q in queue)
        for ret in self.records.open("ret"):
            if ret.state == "in_transit":
                v += ret.data["qty"] * product_standard[ret.data["sku"]]
        return v

    # -- actions and the day -------------------------------------------------
    def exception(self, kind, ref, text): self.exceptions.append({"day": self.day, "kind": kind, "ref": ref, "text": text})
    def log(self, text): self.day_log.append(text)
    def apply(self, action: dict) -> dict:
        if self.done: return {"ok": False, "reason": "episode finished", "id": None}
        if not isinstance(action, dict):
            return {"ok": False, "reason": "action must be a mapping", "id": None}
        kind = action.get("type")
        if not isinstance(kind, str):
            return {"ok": False, "reason": "action type must be a string", "id": None}
        if kind not in self.actions: return {"ok": False, "reason": f"unknown action {kind!r}", "id": None}
        try:
            out = self.actions[kind][1](self, action) or {}
            return {"ok": True, "reason": "", "id": out.get("id"), **{k: v for k, v in out.items() if k != "id"}}
        except (ValueError, KeyError, IllegalTransition) as e:
            return {"ok": False, "reason": str(e), "id": None}

    def end_day(self) -> dict:
        if self.done: raise RuntimeError("episode finished")
        start_exceptions, start_news, self.day_log = len(self.exceptions), len(self.news), []
        self.news += self.cond.advance(self.day)
        for m in self.modules: m.advance(self)
        self.ledger.holding_charge(self.day, self.inventory_value())
        report = {"day": self.day, "date": cal.to_date(self.day).isoformat(), "log": list(self.day_log), "cash": round(self.ledger.cash, 2),
                  "new_exceptions": self.exceptions[start_exceptions:], "news": self.news[start_news:]}
        self.day += 1; self.done = self.day >= cal.N_DAYS
        return report

    def screens(self) -> dict:
        from . import screens
        return screens.build(self)

    def export(self) -> dict:
        return {"seed": self.seed, "day": self.day, "cash": self.ledger.cash, "stock": self.stock, "hidden": self.cond.to_dict(),
                "records": [r.__dict__ for r in (self.records.get(i) for i in self.records.ids())],
                "ledger": [list(line) for line in self.ledger.lines],
                "news": self.news, "exceptions": self.exceptions}
