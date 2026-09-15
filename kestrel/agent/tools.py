"""Tool schemas, system briefing, and dispatch for the plain tool-calling model player (Task 18).

Every tool name below is either an engine action (a key of some module's ACTIONS dict --
procurement, logistics, plant, distribution, fulfilment) or one of the two control tools
get_screen / end_day. Schemas are derived from each action function's own validation code,
not guessed, so a well-formed tool call is always accepted by world.apply.
"""
import json

from .. import calendar as cal
from ..finance import HOLDING_RATE
from ..logistics import BLANK_SAILING_PROB, DEMURRAGE_RATE, DEMURRAGE_RATE_LATE, ROLL_PROB, ROLL_PROB_TIGHT
from ..network import COMPONENTS, CUSTOMERS, DCS, LEGS, NODES, PRODUCTS, SUPPLIERS
from ..records import CLOSED, LEGAL
from ..world import OPENING_CASH

SUPPLIER_IDS = list(SUPPLIERS)
COMPONENT_IDS = list(COMPONENTS)
SKU_IDS = list(PRODUCTS)
CUSTOMER_IDS = list(CUSTOMERS)
NODE_IDS = list(NODES)
LEG_MODES = sorted({mode for _, _, mode in LEGS})
RECORD_KINDS = sorted(CLOSED)
# Fixed by kestrel/screens.py::build's return dict -- these keys do not vary by task or seed.
SCREEN_NAMES = ["calendar", "inventory", "records", "exceptions", "news", "market", "suppliers", "customers", "finance", "forecast"]

ENGINE_TOOLS = {
    "create_po": {
        "description": "Place a purchase order for a component with one of its qualified suppliers.",
        "parameters": {
            "type": "object",
            "properties": {
                "supplier": {"type": "string", "enum": SUPPLIER_IDS},
                "component": {"type": "string", "enum": COMPONENT_IDS},
                "qty": {"type": "integer", "description": "must be a positive integer at or above the supplier's MOQ for this component"},
                "requested_day": {"type": "integer", "description": "absolute day number wanted; defaults to today+30"},
                "incoterm": {"type": "string", "description": "defaults to FOB"},
            },
            "required": ["supplier", "component", "qty"],
        },
    },
    "cancel_po": {
        "description": "Cancel a purchase order still in draft, confirmed, or in_production state.",
        "parameters": {"type": "object", "properties": {"po_id": {"type": "string"}}, "required": ["po_id"]},
    },
    "expedite_po": {
        "description": "Pay 5% of PO value for a chance to pull in a confirmed or in_production PO's ship/promise day.",
        "parameters": {"type": "object", "properties": {"po_id": {"type": "string"}}, "required": ["po_id"]},
    },
    "accept_invoice": {
        "description": "Accept an open or blocked inbound invoice and settle it.",
        "parameters": {"type": "object", "properties": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]},
    },
    "dispute_invoice": {
        "description": "Dispute an open or blocked inbound invoice; resolves 10 days later at -6%.",
        "parameters": {"type": "object", "properties": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]},
    },
    "set_inspection_level": {
        "description": "Set the AQL inspection level used for a supplier's incoming lots.",
        "parameters": {
            "type": "object",
            "properties": {"supplier": {"type": "string", "enum": SUPPLIER_IDS}, "level": {"type": "string", "enum": ["I", "II", "III"]}},
            "required": ["supplier", "level"],
        },
    },
    "qualify_supplier": {
        "description": "Start a 45-day supplier qualification.",
        "parameters": {"type": "object", "properties": {"supplier": {"type": "string", "enum": SUPPLIER_IDS}}, "required": ["supplier"]},
    },
    "request_audit": {
        "description": "Pay for a 3-day supplier audit; reveals the supplier's health once complete.",
        "parameters": {"type": "object", "properties": {"supplier": {"type": "string", "enum": SUPPLIER_IDS}}, "required": ["supplier"]},
    },
    "return_lot": {
        "description": "Return a rejected, still-quarantined lot to its supplier for a credit note.",
        "parameters": {"type": "object", "properties": {"lot_id": {"type": "string"}}, "required": ["lot_id"]},
    },
    "book_container": {
        "description": "Book ocean, air, or sea_air freight for finished goods from PLANT to DC-NL.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["ocean", "air", "sea_air"]},
                "route": {"type": "string", "enum": ["suez", "cape"], "description": "required only when mode is ocean"},
                "lines": {"type": "object", "description": "map of sku -> positive integer quantity, drawn from PLANT stock",
                          "additionalProperties": {"type": "integer"}},
                "rate_type": {"type": "string", "enum": ["spot", "contract"], "description": "defaults to spot; contract only valid for ocean with an active freight contract"},
            },
            "required": ["mode", "lines"],
        },
    },
    "cancel_booking": {
        "description": "Cancel a booking still in booked or cut_off state; freight/surcharges already paid are not refunded.",
        "parameters": {"type": "object", "properties": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    },
    "sign_freight_contract": {
        "description": "Sign a 12-month ocean freight contract at 80% of the spot rate. Only allowed 1-15 May.",
        "parameters": {"type": "object", "properties": {"containers_per_month": {"type": "integer", "description": "minimum commitment per month, must be >= 4"}},
                       "required": ["containers_per_month"]},
    },
    "release_work_order": {
        "description": "Release a plant work order to assemble finished goods from components already on hand at PLANT.",
        "parameters": {"type": "object", "properties": {"sku": {"type": "string", "enum": SKU_IDS}, "qty": {"type": "integer"}}, "required": ["sku", "qty"]},
    },
    "cancel_work_order": {
        "description": "Cancel a planned or released work order and return its reserved components to stock.",
        "parameters": {"type": "object", "properties": {"work_order_id": {"type": "string"}}, "required": ["work_order_id"]},
    },
    "create_transfer": {
        "description": "Move finished goods between nodes by rail, truck, or air on an existing route.",
        "parameters": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "enum": NODE_IDS},
                "dst": {"type": "string", "enum": NODE_IDS},
                "mode": {"type": "string", "enum": LEG_MODES},
                "lines": {"type": "object", "description": "map of sku -> positive integer quantity, drawn from src stock",
                          "additionalProperties": {"type": "integer"}},
            },
            "required": ["src", "dst", "mode", "lines"],
        },
    },
    "set_allocation_policy": {
        "description": "Set how open stock is allocated to competing customer orders.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["priority", "fair_share"]},
                "order": {"type": "array", "items": {"type": "string", "enum": CUSTOMER_IDS},
                          "description": "priority order; must list every customer exactly once"},
            },
            "required": ["mode"],
        },
    },
    "allocate_order": {
        "description": "Manually allocate stock to a received order.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["order_id", "qty"]},
    },
    "decline_order": {
        "description": "Decline a received order outright, releasing any partial allocation.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
    "markdown": {
        "description": "Mark down a SKU's price by 1-60%, boosting its demand.",
        "parameters": {"type": "object", "properties": {"sku": {"type": "string", "enum": SKU_IDS}, "percent": {"type": "integer"}}, "required": ["sku", "percent"]},
    },
}

CONTROL_TOOLS = {
    "get_screen": {
        "description": "Read one named public screen in full (the day's opening message already contains overview/exceptions/news). "
                        "The records screen is large (every open business document, full history included); pass kind to get back "
                        "only one record kind (e.g. kind=\"po\") instead of the whole thing. kind is ignored for every other screen.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "enum": SCREEN_NAMES},
            "kind": {"type": "string", "enum": RECORD_KINDS,
                     "description": "optional; only applies when name is \"records\" -- filters the records screen to this one record kind"},
        }, "required": ["name"]},
    },
    "end_day": {
        "description": "Finish the current day. Must be called once you are done acting for today.",
        "parameters": {"type": "object", "properties": {"note": {"type": "string", "description": "short rationale for today's actions, kept in the run's record"}}, "required": ["note"]},
    },
}

TOOL_NAMES = list(ENGINE_TOOLS) + list(CONTROL_TOOLS)


def tool_schemas() -> list[dict]:
    """OpenAI-compatible chat-completions `tools` list."""
    out = []
    for name, spec in {**ENGINE_TOOLS, **CONTROL_TOOLS}.items():
        out.append({"type": "function", "function": {"name": name, "description": spec["description"], "parameters": spec["parameters"]}})
    return out


def parse_tool_arguments(raw: str) -> tuple[dict | None, str | None]:
    """Parse a tool call's JSON argument string. Returns (args, None) or (None, error)."""
    try:
        args = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        return None, f"malformed tool call arguments: {e}"
    if not isinstance(args, dict):
        return None, f"tool call arguments must be a JSON object, got {type(args).__name__}"
    return args, None


def call_tool(world, name: str, args: dict) -> dict:
    """Dispatch one already-parsed tool call. end_day is handled by the caller, not here."""
    if name == "get_screen":
        screens = world.screens()
        screen_name = args.get("name")
        if screen_name not in screens:
            return {"ok": False, "reason": f"unknown screen {screen_name!r}; expected one of {SCREEN_NAMES}", "id": None}
        result = screens[screen_name]
        kind = args.get("kind")
        if kind is not None and screen_name == "records":
            if kind not in RECORD_KINDS:
                return {"ok": False, "reason": f"unknown record kind {kind!r}; expected one of {RECORD_KINDS}", "id": None}
            result = {kind: result[kind], "closed_counts": {kind: result["closed_counts"][kind]}}
        return result
    if name not in ENGINE_TOOLS:
        return {"ok": False, "reason": f"unknown tool {name!r}", "id": None}
    return world.apply({"type": name, **args})


def build_system_brief(task_brief: dict) -> str:
    """The operational briefing: network, calendar, record states, unit economics, information
    limits, and actions -- built from public config constants so it never goes stale."""
    lines = [
        "You are the supply planner for Kestrel Audio. You play one day at a time; nothing "
        "advances until you call end_day. Every action below is a real business document or "
        "commitment -- there is no free-form execution, only the tools listed at the end.",
        "",
        f"Task: {task_brief['id']} (starts day {task_brief['start_day']}, runs {task_brief['days']} days). "
        f"{task_brief['public_brief']}",
        "",
        "== Products (SKU: name, price EUR, ABC class, BOM, assembly cost EUR/unit, units/container, units/pallet) ==",
    ]
    for sku, p in PRODUCTS.items():
        lines.append(f"- {sku}: {p.name}, price {p.price}, class {p.abc}, BOM {dict(p.bom)}, "
                      f"assembly {p.assembly_cost}/unit, {p.per_container}/container, {p.per_pallet}/pallet.")
    lines += ["", "== Suppliers (location, components, MOQ, price breaks, nominal lead days, road transit, deposit, qualified) =="]
    for sid, s in SUPPLIERS.items():
        lines.append(f"- {sid} ({s.location}): {list(s.components)}, MOQ {dict(s.moq)}, price breaks {dict(s.breaks)}, "
                      f"nominal lead days {dict(s.lead_days)}, road transit {s.road_days}d, deposit {s.deposit_pct*100:.0f}% up front, "
                      f"qualified at start={s.qualified}. Actual confirmed quantity/lead/ship day can differ from nominal; "
                      f"only the po/booking/lot/invoice records and the suppliers screen show what actually happened.")
    lines += ["", "== Customers (DC served, share of demand, chargeback rule, backorder window, payment terms) =="]
    for cid, c in CUSTOMERS.items():
        lines.append(f"- {cid}: served from {c.dc}, ~{c.share*100:.0f}% of demand, chargeback rule '{c.chargeback}', "
                      f"backorder window {c.backorder_days}d, payment terms {c.payment_days}d.")
    lines += ["", "== Freight routes and inter-DC legs (mean transit days, cost basis) =="]
    for (src, dst, mode), leg in LEGS.items():
        lines.append(f"- {src} -> {dst} via {mode}: ~{leg['mean']}d, cost {leg['cost']}.")
    lines += ["", "== Calendar events this year =="]
    for e in cal.EVENTS:
        lines.append(f"- {e['name']}: {cal.to_date(e['start_day'])} to {cal.to_date(e['end_day'])} (day {e['start_day']}-{e['end_day']}): {e['note']}.")
    lines += ["", "== Business documents (record types) and the states each can legally move through =="]
    for rtype, transitions in LEGAL.items():
        if transitions:
            lines.append(f"- {rtype}: " + ", ".join(f"{a}->{b}" for a, b in sorted(transitions)))
    lines += [
        "",
        "== Unit economics ==",
        f"Opening cash {OPENING_CASH:,.0f} EUR. Daily holding charge {HOLDING_RATE*100:.0f}%/year on standard-cost "
        f"inventory value (on-hand, WIP, quarantine, and owned transit). Demurrage on a container starts after 6 "
        f"free days past arrival at {DEMURRAGE_RATE}/container/day, rising to {DEMURRAGE_RATE_LATE}/container/day "
        f"after 11 days. Ocean bookings roll to the next sailing with probability {ROLL_PROB} normally, "
        f"{ROLL_PROB_TIGHT} when the shipping corridor is congested or diverted; a blank sailing (prob {BLANK_SAILING_PROB}/day) "
        "delays affected cut-offs a week. Chargebacks are deducted per customer's rule (otif3/late2/asn_tiers) "
        "on late or short delivered orders; see each customer's screen entry for chargebacks to date.",
        "",
        "== What you can observe ==",
        "Each day's opening message gives you the calendar, exceptions, and news screens. Call get_screen(name) "
        f"for any of: {SCREEN_NAMES}. Every business document (PO, booking, work order, order, invoice, lot, "
        "transfer, credit note, qualification, audit, chargeback) is visible in full once created, including its "
        "full history of state transitions. The records screen is large; call get_screen(\"records\", kind=...) "
        f"with one of {RECORD_KINDS} to fetch just one record kind instead of all of them.",
        "",
        "== What you cannot observe ==",
        "True supplier health, the exact freight rate regime, port congestion levels, and all random-number "
        "internals are hidden. You only see their downstream effects: confirmed quantities, ship/promise slips, "
        "lot dppm and AQL outcomes, invoice mismatches, booking rolls, demurrage, and scorecards.",
        "",
        "== Actions ==",
        "Tools: " + ", ".join(TOOL_NAMES) + ". A malformed or rejected tool call costs you a call but does not end "
        "the day; you can retry. You must call end_day(note=...) to finish today, giving a short rationale for what "
        "you did (or did not do). There is a hard cap on tool calls per day; hitting it ends the day automatically "
        "with note='cap reached'.",
    ]
    return "\n".join(lines)
