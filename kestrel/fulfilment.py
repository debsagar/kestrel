"""Customer orders, stock allocation, delivery, chargebacks, and returns."""
from . import calendar as cal
from .demand import PROMO_DISCOUNT
from .network import CUSTOMERS, PRODUCTS, component_cost
from .records import transition


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int, got {value!r}")
    return value


def set_allocation_policy(world, action):
    mode = action.get("mode")
    if mode not in ("priority", "fair_share"):
        raise ValueError(f"unknown allocation mode {mode!r}")
    order = action.get("order", world.allocation_policy["order"])
    if (not isinstance(order, list) or not all(isinstance(customer, str) for customer in order)
            or len(order) != len(CUSTOMERS)
            or set(order) != set(CUSTOMERS)):
        raise ValueError("order must list every customer exactly once")
    world.allocation_policy["mode"] = mode
    world.allocation_policy["order"] = list(order)


def allocate_order(world, action):
    order_id = action.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError("order_id is required")
    qty = _positive_int(action.get("qty"), "qty")
    try:
        order = world.records.get(order_id)
    except KeyError:
        raise KeyError(f"no such order {order_id!r}")
    if order.type != "order" or order.state != "received":
        raise ValueError(f"order {order_id} cannot be allocated from state {order.state!r}")
    remaining = order.data["qty"] - order.data["allocated_qty"]
    if qty > remaining:
        raise ValueError(f"order {order_id} has {remaining} units open, cannot allocate {qty}")
    dc, sku = CUSTOMERS[order.data["customer"]].dc, order.data["sku"]
    available = world.stock[dc][sku] - world.allocated[dc][sku]
    if qty > available:
        raise ValueError(f"{dc} has {available} unallocated {sku}, need {qty}")
    order.data["allocated_qty"] += qty
    world.allocated[dc][sku] += qty
    if order.data["allocated_qty"] == order.data["qty"]:
        transition(order, "allocated", world.day, "fully allocated")
        order.data["allocation_day"] = world.day
    return {"id": order.id}


def decline_order(world, action):
    order_id = action.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError("order_id is required")
    try:
        order = world.records.get(order_id)
    except KeyError:
        raise KeyError(f"no such order {order_id!r}")
    if order.type != "order" or order.state != "received":
        raise ValueError(f"order {order_id} cannot be declined from state {order.state!r}")
    dc, sku = CUSTOMERS[order.data["customer"]].dc, order.data["sku"]
    world.allocated[dc][sku] -= order.data["allocated_qty"]
    order.data["allocated_qty"] = 0
    transition(order, "declined", world.day, "declined by planner")
    return {"id": order.id}


def markdown(world, action):
    sku = action.get("sku")
    if sku not in PRODUCTS:
        raise ValueError(f"unknown sku {sku!r}")
    percent = _positive_int(action.get("percent"), "percent")
    if percent > 60:
        raise ValueError(f"percent must be 1-60, got {percent}")
    world.markdown[sku] = 1 - percent / 100
    world.demand.markdown[sku] = 1 + percent / 100 * 1.75


ACTIONS = {"set_allocation_policy": set_allocation_policy, "allocate_order": allocate_order,
           "decline_order": decline_order, "markdown": markdown}


def _new_orders(world):
    day = world.day
    if not cal.is_working("customer", day):
        return
    for customer, terms in CUSTOMERS.items():
        for sku, product in PRODUCTS.items():
            qty = world.demand.order_qty(day, sku, customer)
            if qty <= 0:
                continue
            promo = any(p["customer"] == customer and p["sku"] == sku and p["start_day"] <= day <= p["end_day"]
                        for p in world.demand.promos)
            unit_price = product.price * world.markdown.get(sku, 1.0) * (1 - PROMO_DISCOUNT if promo else 1)
            world.records.new("order", day, "received", customer=customer, sku=sku, qty=qty,
                              allocated_qty=0, shipped_qty=0, requested_day=day + 5,
                              ship_day=None, deliver_day=None, late=False, short=False,
                              value=qty * unit_price, backorder_until=day + (terms.backorder_days or 0),
                              invoice_id=None)


def _reserve(order, world, qty):
    dc, sku = CUSTOMERS[order.data["customer"]].dc, order.data["sku"]
    order.data["allocated_qty"] += qty
    world.allocated[dc][sku] += qty


def _allocate(world):
    day = world.day
    for dc in {c.dc for c in CUSTOMERS.values()}:
        for sku in PRODUCTS:
            orders = [o for o in world.records.open("order") if o.state == "received"
                      and CUSTOMERS[o.data["customer"]].dc == dc and o.data["sku"] == sku]
            available = world.stock[dc][sku] - world.allocated[dc][sku]
            if available > 0 and orders:
                if world.allocation_policy["mode"] == "priority":
                    rank = {c: i for i, c in enumerate(world.allocation_policy["order"])}
                    orders.sort(key=lambda o: (rank[o.data["customer"]], o.created_day, o.id))
                    for order in orders:
                        qty = min(available, order.data["qty"] - order.data["allocated_qty"])
                        _reserve(order, world, qty); available -= qty
                else:
                    orders.sort(key=lambda o: (o.created_day, o.id))
                    open_qty = [o.data["qty"] - o.data["allocated_qty"] for o in orders]
                    allocatable = min(available, sum(open_qty))
                    shares = [allocatable * qty // sum(open_qty) for qty in open_qty]
                    remainder = allocatable - sum(shares)
                    for i in range(remainder):
                        shares[i % len(shares)] += 1
                    for order, qty in zip(orders, shares):
                        _reserve(order, world, qty)
            for order in orders:
                full = order.data["allocated_qty"] == order.data["qty"]
                expired = day >= order.data["backorder_until"]
                if full or expired:
                    order.data["short"] = not full
                    transition(order, "allocated", day, "fully allocated" if full else "backorder expired")
                    order.data["allocation_day"] = day - 1 if order.data["customer"] == "C-WEB" else day


def _ship(world):
    day = world.day
    if not cal.is_working("dc", day):
        return
    for order in world.records.open("order"):
        if order.state != "allocated" or order.data["allocation_day"] >= day:
            continue
        dc, sku, qty = CUSTOMERS[order.data["customer"]].dc, order.data["sku"], order.data["allocated_qty"]
        if qty:
            world.take_stock(dc, sku, qty)
            world.allocated[dc][sku] -= qty
            world.flows["shipped_customers"] += qty
        order.data.update(shipped_qty=qty, ship_day=day, deliver_day=day + 2)
        transition(order, "shipped", day, "shipped to customer")


def _chargeback(world, order):
    rule = CUSTOMERS[order.data["customer"]].chargeback
    rate = 0.0
    if rule == "otif3" and (order.data["late"] or order.data["short"]):
        rate = .03
    elif rule == "late2" and order.data["late"]:
        rate = .02
    elif rule == "asn_tiers" and (order.data["late"] or order.data["short"]):
        recent = [o for o in world.records.all("order") if o.data["customer"] == order.data["customer"]
                  and o.state == "delivered" and o.data["deliver_day"] >= world.day - 29]
        accuracy = 1 - sum(o.data["late"] or o.data["short"] for o in recent) / len(recent)
        rate = .02 if accuracy > .95 else .04 if accuracy >= .70 else .06
    if rate:
        amount = round(order.data["value"] * rate, 2)
        rec = world.records.new("chargeback", world.day, "open", order_id=order.id,
                                amount=amount, due_day=world.day + 30)
        world.ledger.post(world.day, "chargebacks", -amount, rec.id)


def _deliver(world):
    day = world.day
    for order in world.records.open("order"):
        if order.state != "shipped" or order.data["deliver_day"] > day:
            continue
        transition(order, "delivered", day, "delivered to customer")
        order.data["late"] = day > order.data["requested_day"]
        qty, shipped = order.data["qty"], order.data["shipped_qty"]
        value = order.data["value"] * shipped / qty
        world.ledger.post(day, "revenue", value, order.id)
        unit_cost = component_cost(order.data["sku"]) + PRODUCTS[order.data["sku"]].assembly_cost
        world.ledger.post(day, "cogs_components", -(component_cost(order.data["sku"]) * shipped), order.id)
        world.ledger.post(day, "cogs_assembly", -(PRODUCTS[order.data["sku"]].assembly_cost * shipped), order.id)
        terms = CUSTOMERS[order.data["customer"]]
        invoice = world.records.new("invoice_out", day, "open", order_id=order.id, amount=value, due_day=day + terms.payment_days)
        order.data["invoice_id"] = invoice.id
        if terms.payment_days == 0:
            transition(invoice, "paid", day, "paid at delivery")
            world.ledger.post(day, "customer_receipt", value, invoice.id)
        _chargeback(world, order)
        returned = round(shipped * .09)
        if returned:
            world.records.new("ret", day, "in_transit", order_id=order.id, customer=order.data["customer"],
                              sku=order.data["sku"], qty=returned, unit_price=order.data["value"] / qty,
                              unit_cost=unit_cost, arrive_day=day + world.rng_ops.randint(5, 30))


def _receivables(world):
    for invoice in world.records.open("invoice_out"):
        if invoice.state == "open" and invoice.data["due_day"] <= world.day:
            transition(invoice, "paid", world.day, "customer paid")
            world.ledger.post(world.day, "customer_receipt", invoice.data["amount"], invoice.id)
    for chargeback in world.records.open("chargeback"):
        if chargeback.state == "open" and chargeback.data["due_day"] <= world.day:
            transition(chargeback, "paid", world.day, "chargeback settled")
            world.ledger.post(world.day, "customer_receipt", -chargeback.data["amount"], chargeback.id)


def _returns(world):
    day = world.day
    for ret in world.records.open("ret"):
        if ret.state != "in_transit" or ret.data["arrive_day"] > day:
            continue
        good = ret.data["qty"] // 2
        bad = ret.data["qty"] - good
        ret.data.update(restocked_qty=good, written_off_qty=bad)
        dc = CUSTOMERS[ret.data["customer"]].dc
        if good:
            world.add_stock(dc, ret.data["sku"], good)
            world.flows["restocked"] += good
            transition(ret, "restocked", day, "saleable units restocked")
        else:
            transition(ret, "written_off", day, "returned units written off")
        world.flows["written_off"] += bad
        world.flows["returned_lots"] += 1
        world.ledger.post(day, "cogs_components", component_cost(ret.data["sku"]) * ret.data["qty"], ret.id)
        world.ledger.post(day, "cogs_assembly", PRODUCTS[ret.data["sku"]].assembly_cost * ret.data["qty"], ret.id)
        if bad:
            world.ledger.post(day, "writeoffs", -(ret.data["unit_cost"] * bad), ret.id)
        world.ledger.post(day, "returns", -(40 * ret.data["qty"]), ret.id)
        credit = ret.data["qty"] * ret.data["unit_price"]
        note = world.records.new("credit_note", day, "open", order_id=ret.data["order_id"], amount=credit)
        world.ledger.post(day, "revenue", -credit, note.id)
        world.ledger.post(day, "customer_receipt", -credit, note.id)
        transition(note, "paid", day, "customer refunded")


def advance(world):
    _new_orders(world)
    _allocate(world)
    _ship(world)
    _deliver(world)
    _receivables(world)
    _returns(world)


def seed_opening(world):
    pass


def otif(world, customer, day_from=0):
    if customer not in CUSTOMERS:
        raise ValueError(f"unknown customer {customer!r}")
    orders = [o for o in world.records.all("order") if o.state == "delivered" and o.data["customer"] == customer
              and o.data["deliver_day"] >= day_from]
    return sum(not o.data["late"] and not o.data["short"] for o in orders) / len(orders) if orders else 0.0


def fill_rate(world):
    orders = [o for o in world.records.all("order") if o.state in ("delivered", "declined")]
    return sum(o.data["shipped_qty"] for o in orders) / sum(o.data["qty"] for o in orders) if orders else 0.0


def lost_sales(world):
    return sum(o.data["qty"] - o.data["shipped_qty"] for o in world.records.all("order")
               if o.state in ("delivered", "declined") and o.data["customer"] == "C-WEB")
