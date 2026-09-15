from kestrel import fulfilment as ful
from kestrel.network import PRODUCTS, component_cost
from kestrel.world import World


def quiet(world):
    world.demand.order_qty = lambda day, sku, customer: 0


def days(world, count):
    for _ in range(count):
        world.end_day()


def order(world, customer, qty, *, requested_day=5, backorder_until=14, value=None):
    sku = "EB-STD"
    return world.records.new(
        "order", world.day, "received", customer=customer, sku=sku, qty=qty,
        allocated_qty=0, shipped_qty=0, requested_day=requested_day,
        ship_day=None, deliver_day=None, late=False, short=False,
        value=value if value is not None else qty * PRODUCTS[sku].price,
        backorder_until=backorder_until, invoice_id=None,
    )


def empty_dcs(world):
    for dc in world.allocated:
        for sku in PRODUCTS:
            world.stock[dc][sku] = 0


def test_order_allocates_ships_delivers_and_posts_standard_cost():
    w = World(1); quiet(w); empty_dcs(w)
    w.stock["DC-DE"]["EB-STD"] = 100
    o = order(w, "C-BIGBOX", 100)
    days(w, 4)
    assert o.state == "delivered" and o.data["invoice_id"]
    assert w.ledger.total("revenue") == 4900
    assert w.ledger.total("cogs_components") == -100 * component_cost("EB-STD")
    assert w.ledger.total("cogs_assembly") == -250


def test_priority_and_fair_share_preserve_carried_reservations():
    w = World(2); quiet(w); empty_dcs(w)
    w.stock["DC-DE"]["EB-STD"] = 100
    web = order(w, "C-WEB", 100, backorder_until=10)
    big = order(w, "C-BIGBOX", 100)
    w.end_day()
    assert (big.data["allocated_qty"], web.data["allocated_qty"]) == (100, 0)

    w = World(3); quiet(w); empty_dcs(w)
    assert w.apply({"type": "set_allocation_policy", "mode": "fair_share"})["ok"]
    w.stock["DC-DE"]["EB-STD"] = 100
    a = order(w, "C-WEB", 100, backorder_until=10)
    b = order(w, "C-BIGBOX", 300)
    a.data["allocated_qty"] = 20
    w.allocated["DC-DE"]["EB-STD"] = 20
    w.end_day()
    assert (a.data["allocated_qty"], b.data["allocated_qty"]) == (37, 63)
    assert w.allocated["DC-DE"]["EB-STD"] == 100


def test_custom_priority_order_is_validated_and_used():
    w = World(9); quiet(w); empty_dcs(w)
    custom = ["C-WEB", "C-MARKET", "C-BIGBOX", "C-PLCHAIN"]
    assert w.apply({"type": "set_allocation_policy", "mode": "priority", "order": custom})["ok"]
    w.stock["DC-DE"]["EB-STD"] = 10
    web = order(w, "C-WEB", 10, backorder_until=10)
    big = order(w, "C-BIGBOX", 10)
    w.end_day()
    assert web.data["allocated_qty"] == 10 and big.data["allocated_qty"] == 0

    before = {"mode": w.allocation_policy["mode"], "order": list(w.allocation_policy["order"])}
    result = w.apply({"type": "set_allocation_policy", "mode": "fair_share",
                      "order": ["C-WEB", "C-WEB", "C-BIGBOX", "C-PLCHAIN"]})
    assert not result["ok"] and w.allocation_policy == before
    result = w.apply({"type": "set_allocation_policy", "mode": "fair_share",
                      "order": [["C-WEB"], "C-MARKET", "C-BIGBOX", "C-PLCHAIN"]})
    assert not result["ok"] and w.allocation_policy == before


def test_chargeback_record_is_linked_to_late_order_and_amount():
    w = World(4); quiet(w); empty_dcs(w)
    o = order(w, "C-BIGBOX", 100, requested_day=2, value=4900)
    days(w, 3)
    w.stock["DC-DE"]["EB-STD"] = 100
    days(w, 4)
    chargeback = w.records.all("chargeback")[0]
    assert o.state == "delivered" and o.data["late"]
    assert chargeback.data["order_id"] == o.id
    assert chargeback.data["amount"] == 147


def test_fully_short_order_chargeback_uses_original_order_value():
    w = World(10); quiet(w); empty_dcs(w)
    o = order(w, "C-BIGBOX", 100, requested_day=5, backorder_until=0, value=4900)
    days(w, 4)
    chargeback = w.records.all("chargeback")[0]
    assert o.state == "delivered" and o.data["short"] and o.data["shipped_qty"] == 0
    assert chargeback.data["order_id"] == o.id and chargeback.data["amount"] == 147


def test_web_short_is_lost_sale_and_metrics_are_bounded():
    w = World(5); quiet(w); empty_dcs(w)
    o = order(w, "C-WEB", 10, backorder_until=0)
    days(w, 3)
    assert o.state == "delivered" and o.data["short"]
    assert ful.lost_sales(w) == 10 and ful.fill_rate(w) == 0
    assert ful.otif(w, "C-WEB") == 0


def test_markdown_and_manual_actions_validate_before_mutation():
    w = World(6); quiet(w)
    original = dict(w.allocation_policy)
    assert not w.apply({"type": "set_allocation_policy", "mode": "random"})["ok"]
    assert w.allocation_policy == original
    assert not w.apply({"type": "markdown", "sku": "EB-STD", "percent": 1.5})["ok"]
    assert "EB-STD" not in w.markdown
    assert w.apply({"type": "markdown", "sku": "EB-STD", "percent": 20})["ok"]
    assert w.markdown["EB-STD"] == .8 and w.demand.markdown["EB-STD"] == 1.35


def test_return_refunds_cash_and_reverses_cost_before_writeoff():
    w = World(7); quiet(w); empty_dcs(w)
    w.stock["DC-DE"]["EB-STD"] = 100
    o = order(w, "C-WEB", 100)
    days(w, 3)
    ret = w.records.all("ret")[0]
    ret.data["arrive_day"] = w.day
    cash_before = w.ledger.cash
    w.end_day()
    returned = ret.data["qty"]
    assert w.ledger.cash == cash_before - returned * (PRODUCTS["EB-STD"].price + 40)
    assert w.records.all("credit_note")[0].state == "paid"
    assert w.stock["DC-DE"]["EB-STD"] == returned // 2
    assert w.ledger.total("cogs_components") == -(100 - returned) * component_cost("EB-STD")


def test_declining_partially_reserved_order_releases_reservation():
    w = World(8); quiet(w); empty_dcs(w)
    w.stock["DC-DE"]["EB-STD"] = 20
    o = order(w, "C-BIGBOX", 100)
    assert w.apply({"type": "allocate_order", "order_id": o.id, "qty": 20})["ok"]
    assert w.apply({"type": "decline_order", "order_id": o.id})["ok"]
    assert o.state == "declined" and w.allocated["DC-DE"]["EB-STD"] == 0
