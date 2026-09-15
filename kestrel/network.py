"""Static configuration of the Kestrel network (SPEC §2, §3, §5.4, §5.5). Nothing here changes during a run."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    sku: str; name: str; price: float; abc: str; bom: dict; weight_kg: float
    per_container: int; per_pallet: int; eq_units: int; assembly_cost: float


@dataclass(frozen=True)
class Supplier:
    id: str; location: str; road_days: int; components: tuple; moq: dict; breaks: dict
    lead_days: dict; deposit_pct: float; qualified: bool


@dataclass(frozen=True)
class Customer:
    id: str; dc: str; share: float; chargeback: str; backorder_days: int | None
    payment_days: int; order_weekday: int | None


COMPONENTS = ("BAT", "SOC", "DRV", "CASE", "CHG", "PKG")
_EB = {"BAT": 1, "SOC": 1, "DRV": 2, "CASE": 1, "CHG": 1, "PKG": 1}
PRODUCTS = {
    "EB-STD": Product("EB-STD", "Standard earbuds", 49.0, "A", _EB, 0.12, 8000, 400, 1, 2.50),
    "EB-PRO": Product("EB-PRO", "Pro earbuds", 119.0, "A", _EB, 0.12, 8000, 400, 1, 2.50),
    "SPK-1": Product("SPK-1", "Portable speaker", 89.0, "B", {"BAT": 2, "SOC": 1, "DRV": 1, "CASE": 1, "PKG": 1}, 0.9, 2500, 60, 2, 4.00),
}
SUPPLIERS = {
    "S-BAT": Supplier("S-BAT", "Dongguan", 1, ("BAT",), {"BAT": 5000}, {"BAT": ((5000, 1.80), (20000, 1.65), (50000, 1.50))}, {"BAT": 35}, 0.3, True),
    "S-SOC": Supplier("S-SOC", "Shenzhen", 1, ("SOC",), {"SOC": 2000}, {"SOC": ((2000, 6.50), (10000, 6.00), (30000, 5.60))}, {"SOC": 60}, 0.3, True),
    "S-BRK": Supplier("S-BRK", "Hong Kong", 2, ("SOC",), {"SOC": 500}, {"SOC": ((500, 11.00),)}, {"SOC": 10}, 1.0, False),
    "S-DRV": Supplier("S-DRV", "Haiphong", 3, ("DRV",), {"DRV": 10000}, {"DRV": ((10000, 0.90), (40000, 0.80))}, {"DRV": 45}, 0.3, True),
    "S-CASE": Supplier("S-CASE", "Dongguan", 1, ("CASE", "CHG", "PKG"), {"CASE": 5000, "CHG": 5000, "PKG": 5000},
                       {"CASE": ((5000, 1.40), (20000, 1.25)), "CHG": ((5000, 2.20), (20000, 2.00)), "PKG": ((5000, 0.35), (20000, 0.30))},
                       {"CASE": 30, "CHG": 30, "PKG": 30}, 0.3, True),
}
CUSTOMERS = {
    "C-BIGBOX": Customer("C-BIGBOX", "DC-DE", 0.35, "otif3", 14, 45, 0),
    "C-MARKET": Customer("C-MARKET", "DC-DE", 0.30, "asn_tiers", 7, 30, None),
    "C-PLCHAIN": Customer("C-PLCHAIN", "DC-PL", 0.20, "late2", 14, 30, 0),
    "C-WEB": Customer("C-WEB", "DC-DE", 0.15, "none", None, 0, None),
}
DCS = ("DC-NL", "DC-DE", "DC-PL")
NODES = ("PLANT",) + DCS
PRIMARY_SUPPLIER = {"BAT": "S-BAT", "SOC": "S-SOC", "DRV": "S-DRV", "CASE": "S-CASE", "CHG": "S-CASE", "PKG": "S-CASE"}
# (from, to, mode) -> transit mean/sd in days and cost unit (SPEC §3, §5.2, §5.4)
LEGS = {
    ("PLANT", "DC-NL", "ocean_suez"): {"mean": 30, "sd": 1.5, "cost": "rate"},
    ("PLANT", "DC-NL", "ocean_cape"): {"mean": 42, "sd": 2.0, "cost": "rate"},
    ("PLANT", "DC-NL", "air"): {"mean": 6, "sd": 1.0, "cost": 6.0},        # EUR/kg
    ("PLANT", "DC-NL", "sea_air"): {"mean": 20, "sd": 1.5, "cost": 3.0},   # EUR/kg
    ("DC-NL", "DC-DE", "rail"): {"mean": 1, "sd": 0, "cost": 90.0},        # EUR/pallet
    ("DC-NL", "DC-PL", "rail"): {"mean": 3, "sd": 0.5, "cost": 180.0},
    ("DC-NL", "DC-DE", "truck"): {"mean": 1, "sd": 0, "cost": 117.0},
    ("DC-NL", "DC-PL", "truck"): {"mean": 2, "sd": 0.5, "cost": 234.0},
    ("DC-DE", "DC-PL", "truck"): {"mean": 2, "sd": 0.5, "cost": 200.0},
    ("DC-PL", "DC-DE", "truck"): {"mean": 2, "sd": 0.5, "cost": 200.0},
    ("DC-NL", "DC-DE", "air"): {"mean": 1, "sd": 0, "cost": 1500.0},
    ("DC-NL", "DC-PL", "air"): {"mean": 1, "sd": 0, "cost": 1500.0},
    ("DC-DE", "DC-PL", "air"): {"mean": 1, "sd": 0, "cost": 1500.0},
    ("DC-PL", "DC-DE", "air"): {"mean": 1, "sd": 0, "cost": 1500.0},
}
CUSTOMER_DELIVERY_DAYS = 2
PROMISED_DAYS = 5


def price_for(supplier_id: str, component: str, qty: int) -> float:
    price = None
    for q, p in SUPPLIERS[supplier_id].breaks[component]:
        if qty >= q:
            price = p
    if price is None:
        raise ValueError(f"{qty} below MOQ {SUPPLIERS[supplier_id].moq[component]} for {component} at {supplier_id}")
    return price


def component_cost(sku: str) -> float:
    return sum(q * price_for(PRIMARY_SUPPLIER[c], c, SUPPLIERS[PRIMARY_SUPPLIER[c]].moq[c]) for c, q in PRODUCTS[sku].bom.items())


def pallets(sku: str, qty: int) -> int:
    return -(-qty // PRODUCTS[sku].per_pallet)


def containers(lines: dict) -> int:
    if not lines:
        return 0
    return math.ceil(sum(qty / PRODUCTS[sku].per_container for sku, qty in lines.items()))
