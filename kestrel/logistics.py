"""Container bookings from the plant to DC-NL: cut-off, loading, the voyage, the port, and
demurrage (SPEC S5.2, S3, S6.1-S6.3).

Ocean/air/sea-air all ride the same booking lifecycle
(booked -> cut_off -> loaded -> at_sea -> arrived -> customs -> cleared -> delivered) so the
port queue and demurrage rules apply uniformly; only the freight formula and transit time
differ by mode (task-9 controller ruling).
"""
from . import calendar as cal
from . import network
from .network import PRODUCTS
from .records import transition

ROLL_PROB, ROLL_PROB_TIGHT = 0.08, 0.20
BLANK_SAILING_PROB = 0.01
DEMURRAGE_RATE, DEMURRAGE_RATE_LATE = 60.0, 120.0


def _tight(world) -> bool:
    """Public tightness signal: never reads cond.rate_regime (task-9 controller ruling)."""
    return cal.freight_tight(world.day) or world.cond.lane == "diverted"


def booking_cost(world, mode, route, lines, rate_type) -> dict:
    if mode == "ocean":
        containers = network.containers(lines)
        if rate_type == "contract":
            if world.contract is None or world.contract.state != "active":
                raise ValueError("rate_type 'contract' requires an active freight contract")
            rate = world.contract.data["price"]
        else:
            rate = world.cond.spot_rate()
        freight = containers * rate
        per_container = 500.0                                  # BAF
        if cal.pss_in_season(world.day): per_container += 800.0
        if world.cond.lane == "diverted": per_container += 500.0   # war-risk, public on the booking
        surcharges = containers * per_container
    else:
        weight = sum(qty * PRODUCTS[sku].weight_kg for sku, qty in lines.items())
        freight = weight * (6.0 if mode == "air" else 3.0)
        surcharges = 0.0
    return {"freight": freight, "surcharges": surcharges}


# -- planner actions ----------------------------------------------------------

def book_container(world, a):
    mode = a.get("mode")
    if mode not in ("ocean", "air", "sea_air"):
        raise ValueError(f"unknown mode {mode!r}; expected ocean, air, or sea_air")
    route = a.get("route")
    if mode == "ocean" and route not in ("suez", "cape"):
        raise ValueError("ocean booking requires route 'suez' or 'cape'")
    lines = a.get("lines")
    if not isinstance(lines, dict) or not lines: raise ValueError("lines is required")
    for sku, qty in lines.items():
        if sku not in PRODUCTS: raise ValueError(f"unknown sku {sku!r}")
        if type(qty) is not int or qty <= 0:
            raise ValueError(f"quantity for {sku} must be a positive integer, got {qty!r}")
    lines = dict(lines)
    rate_type = a.get("rate_type", "spot")
    if rate_type not in ("spot", "contract"): raise ValueError(f"unknown rate_type {rate_type!r}")
    if rate_type == "contract" and mode != "ocean":
        raise ValueError("rate_type 'contract' only applies to ocean bookings")
    for sku, qty in lines.items():
        have = world.stock["PLANT"].get(sku, 0)
        if qty > have: raise ValueError(f"PLANT has {have} {sku}, need {qty}")
    cost = booking_cost(world, mode, route, lines, rate_type)   # may raise before any stock moves
    for sku, qty in lines.items():
        world.take_stock("PLANT", sku, qty)
    day, containers = world.day, network.containers(lines)
    if mode == "ocean":
        cutoff_day = day + (world.rng_ops.randint(14, 21) if _tight(world) else 7)
    else:
        cutoff_day = day + 1
    rec = world.records.new(
        "booking", day, "booked", mode=mode, route=route, lines=lines, rate_type=rate_type, containers=containers,
        cutoff_day=cutoff_day, load_day=None, eta_day=None, arrival_day=None, cleared_day=None, free_until=None,
        freight=cost["freight"], surcharges=cost["surcharges"], demurrage_paid=0.0,
    )
    world.ledger.post(day, "freight", -cost["freight"], rec.id)
    world.ledger.post(day, "surcharges", -cost["surcharges"], rec.id)
    if rate_type == "contract":
        world.contract.data["used_this_month"] += containers
    world.log(f"booking {rec.id}: {mode} {lines}, freight {cost['freight']:.2f}, surcharges {cost['surcharges']:.2f}")
    return {"id": rec.id}


def _get_booking(world, a):
    bk_id = a.get("booking_id")
    if not bk_id: raise ValueError("booking_id is required")
    try: return world.records.get(bk_id)
    except KeyError: raise KeyError(f"no such booking {bk_id!r}")


def cancel_booking(world, a):
    bk = _get_booking(world, a)
    if bk.state not in ("booked", "cut_off"):
        raise ValueError(f"booking {bk.id} cannot be cancelled from state {bk.state!r}")
    for sku, qty in bk.data["lines"].items():
        world.add_stock("PLANT", sku, qty)
    transition(bk, "cancelled", world.day, "cancelled by planner; freight/surcharges not refunded")
    return {"id": bk.id}


def sign_freight_contract(world, a):
    if not cal.contract_window(world.day):
        raise ValueError("a freight contract can only be signed 1-15 May")
    if world.contract is not None and world.contract.state == "active":
        raise ValueError("a freight contract is already active")
    cpm = a.get("containers_per_month", 0)
    if type(cpm) is not int or cpm <= 0:
        raise ValueError(f"containers_per_month must be a positive integer, got {cpm!r}")
    if cpm < 4: raise ValueError(f"containers_per_month must be >= 4, got {cpm}")
    price = 0.8 * world.cond.spot_rate()
    rec = world.records.new(
        "contract", world.day, "active", price=price, min_per_month=cpm, used_this_month=0,
        start_day=world.day, end_day=world.day + 365,
    )
    world.contract = rec
    world.log(f"contract {rec.id}: {cpm} containers/month at {price:.2f}")
    return {"id": rec.id}


ACTIONS = {"book_container": book_container, "cancel_booking": cancel_booking, "sign_freight_contract": sign_freight_contract}


# -- daily lifecycle stages ----------------------------------------------------

def _blank_sailings(world):
    day = world.day
    if world.rng_ops.random() < BLANK_SAILING_PROB:
        window = (day + 14, day + 21)
        world.blank_sailings.append(window)
        world.news.append({"day": day, "source": "Carrier", "title": "Blank sailing announced",
                            "body": f"A sailing will be blanked; bookings with cut-off between day {window[0]} "
                                    f"and {window[1]} will be delayed a week.", "kind": "market"})
    for frm, to in world.blank_sailings:
        for bk in world.records.open("booking"):
            if bk.state == "booked" and bk.data["mode"] == "ocean" and frm <= bk.data["cutoff_day"] <= to:
                bk.data["cutoff_day"] += 7
                transition(bk, "blanked", day, "blank sailing")
                transition(bk, "cut_off", day, "cut-off after blank sailing")
                world.exception("booking", bk.id, f"booking {bk.id} hit a blank sailing; new cutoff day {bk.data['cutoff_day']}")


def _load(world):
    day = world.day
    for bk in world.records.open("booking"):
        if bk.state == "booked" and day >= bk.data["cutoff_day"]:
            transition(bk, "cut_off", day, "cut-off reached")
        elif bk.state in ("cut_off", "rolled") and day >= bk.data["cutoff_day"] + 1:
            prob = ROLL_PROB_TIGHT if _tight(world) else ROLL_PROB
            if world.rng_ops.random() < prob:
                bk.data["cutoff_day"] += 7
                if bk.state == "cut_off":
                    transition(bk, "rolled", day, "rolled to next sailing")
                    world.exception("booking", bk.id, f"booking {bk.id} rolled; new cutoff day {bk.data['cutoff_day']}")
                else:
                    bk.history.append((day, bk.state, f"rolled again; new cutoff day {bk.data['cutoff_day']}"))
            else:
                transition(bk, "loaded", day, "loaded")
                bk.data["load_day"] = day
                bk.data["eta_day"] = day + world.cond.transit_days(bk.data["mode"], bk.data["route"], world.rng_ops, day)
                transition(bk, "at_sea", day, "departed")


def _arrive(world):
    day = world.day
    for bk in world.records.open("booking"):
        if bk.state != "at_sea" or day < bk.data["eta_day"]: continue
        transition(bk, "arrived", day, "arrived Rotterdam")
        world.cond.add_arrivals(bk.data["containers"], day)
        bk.data["arrival_day"] = day
        bk.data["free_until"] = day + 5
        bk.data["_customs_ready_day"] = day + world.cond.berth_wait_days()


def _customs(world):
    day = world.day
    for bk in world.records.open("booking"):
        if bk.state == "arrived" and day >= bk.data["_customs_ready_day"]:
            transition(bk, "customs", day, "customs inspection")
            flagged = world.rng_ops.random() < 0.10
            delay = world.rng_ops.randint(3, 5) if flagged else world.rng_ops.randint(1, 2)
            bk.data["cleared_day"] = day + delay
        elif bk.state == "customs" and day >= bk.data["cleared_day"]:
            transition(bk, "cleared", day, "customs cleared")


def _deliver(world):
    """The next DC working day, gated on receiving capacity (ruling: a container waits in
    'cleared' -- and keeps accruing demurrage -- while DC-NL has no receiving capacity)."""
    day = world.day
    if not cal.is_working("dc", day): return
    if world.dc_inbound_capacity["DC-NL"] <= 0: return
    for bk in world.records.open("booking"):
        if bk.state != "cleared": continue
        for sku, qty in bk.data["lines"].items():
            world.dc_inbound_queue["DC-NL"].append((sku, qty))
        transition(bk, "delivered", day, "delivered to DC-NL inbound queue")


def _demurrage(world):
    day = world.day
    for bk in world.records.open("booking"):
        if bk.state not in ("arrived", "customs", "cleared"): continue
        days_since = day - bk.data["arrival_day"]
        if days_since < 6: continue
        rate = DEMURRAGE_RATE_LATE if days_since >= 11 else DEMURRAGE_RATE
        amount = rate * bk.data["containers"]
        world.ledger.post(day, "demurrage", -amount, bk.id)
        bk.data["demurrage_paid"] += amount


def _contract_month_end(world):
    c = world.contract
    if c is None or c.state != "active": return
    if cal.to_date(world.day).day == 1:
        used, minimum, price = c.data["used_this_month"], c.data["min_per_month"], c.data["price"]
        if used < minimum:
            world.ledger.post(world.day, "freight", -(minimum - used) * price, c.id)
        c.data["used_this_month"] = 0
    if world.day >= c.data["end_day"]:
        transition(c, "expired", world.day, "contract term ended")
        world.contract = None


def advance(world):
    _blank_sailings(world)
    _load(world)
    _arrive(world)
    _customs(world)
    _deliver(world)
    _demurrage(world)
    _contract_month_end(world)


def seed_opening(world):
    lines = {"EB-STD": 8000}
    cost = booking_cost(world, "ocean", "suez", lines, "spot")
    rec = world.records.new(
        "booking", 0, "at_sea", mode="ocean", route="suez", lines=lines, rate_type="spot",
        containers=network.containers(lines), cutoff_day=0, load_day=0, eta_day=12, arrival_day=None,
        cleared_day=None, free_until=None, freight=cost["freight"], surcharges=cost["surcharges"], demurrage_paid=0.0,
    )
    world.ledger.post(0, "freight", -cost["freight"], rec.id)
    world.ledger.post(0, "surcharges", -cost["surcharges"], rec.id)
