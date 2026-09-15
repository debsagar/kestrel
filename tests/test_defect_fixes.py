"""Task 19 defect-fix pass (D1-D4, SOURCE_HASH): tests for the scoped fixes made after
live model runs found docs/model-findings.md's four defects. Each test below reproduces
(or targets) the exact defect described there.
"""
import json

import pytest

from kestrel import planner
from kestrel.agent import runner, tasks, tools
from kestrel.records import CLOSED, transition
from kestrel.world import World


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-super-secret-test-key")


# -- D3: asn/receipt now have real terminal states, so Records.open() is finite ----------

def test_d3_asn_and_receipt_have_real_terminal_states():
    world = World(1001)
    for _ in range(60):
        if world.done:
            break
        for action in planner.plan_day(world):
            world.apply(action)
        world.end_day()
    records = world.screens()["records"]
    assert records["closed_counts"]["asn"] > 0, "scenario needs at least one asn ever created"
    assert records["closed_counts"]["receipt"] > 0, "scenario needs at least one receipt ever created"
    assert records["asn"] == [], "asn records should all be in their (now-closed) terminal state"
    assert records["receipt"] == [], "receipt records should all be in their (now-closed) terminal state"
    # the CLOSED sets themselves are no longer empty for these two kinds
    assert CLOSED["asn"] and CLOSED["receipt"]


# -- D1: get_screen(name, kind=...) filters the records screen -------------------------

def test_d1_get_screen_records_kind_filters_to_one_kind():
    world = World(1001)
    for _ in range(5):
        for action in planner.plan_day(world):
            world.apply(action)
        world.end_day()
    full = tools.call_tool(world, "get_screen", {"name": "records"})
    filtered = tools.call_tool(world, "get_screen", {"name": "records", "kind": "po"})
    assert set(filtered) == {"po", "closed_counts"}
    assert filtered["po"] == full["po"]
    assert filtered["closed_counts"] == {"po": full["closed_counts"]["po"]}


def test_d1_get_screen_records_unfiltered_form_still_works():
    world = World(1001)
    result = tools.call_tool(world, "get_screen", {"name": "records"})
    assert "po" in result and "closed_counts" in result


def test_d1_get_screen_unknown_kind_rejected():
    world = World(1001)
    result = tools.call_tool(world, "get_screen", {"name": "records", "kind": "not_a_kind"})
    assert result["ok"] is False and "unknown record kind" in result["reason"]


def test_d1_get_screen_kind_ignored_for_non_records_screen():
    world = World(1001)
    result = tools.call_tool(world, "get_screen", {"name": "inventory", "kind": "po"})
    assert "ok" not in result  # normal inventory screen payload, kind silently irrelevant


def test_d1_kind_described_in_schema_and_briefing():
    schema = tools.ENGINE_TOOLS if False else tools.CONTROL_TOOLS["get_screen"]
    assert "kind" in schema["parameters"]["properties"]
    assert "records screen is large" in schema["description"]
    brief = tools.build_system_brief(tasks.task_public_brief("red_sea"))
    assert "get_screen(\"records\", kind=" in brief


# -- D2: evidence() persisted into run.json for both players ---------------------------

def test_d2_evidence_persisted_in_run_json_luna_and_rule(tmp_path):
    import httpx

    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": None,
                                      "tool_calls": [{"id": "c1", "type": "function",
                                                      "function": {"name": "end_day", "arguments": json.dumps({"note": "done"})}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        })

    transport = httpx.MockTransport(handler)
    rule_result = runner.run("red_sea", "rule", days=3, runs_dir=tmp_path)
    luna_result = runner.run("red_sea", "luna", days=3, runs_dir=tmp_path, transport=transport)

    for player, result in (("rule", rule_result), ("luna", luna_result)):
        run_path = tmp_path / "red_sea" / player / "run.json"
        on_disk = json.loads(run_path.read_text())
        assert "evidence" in on_disk, player
        assert set(on_disk["evidence"]) == {"lane_news", "demurrage_total"}
        assert on_disk["evidence"] == result["evidence"]


def test_d2_baseline_run_also_persists_evidence():
    run = tasks.baseline_run("red_sea")
    assert "evidence" in run
    assert set(run["evidence"]) == {"lane_news", "demurrage_total"}


# -- D4: rolled-booking override retries until a booking exists, bounded to the horizon --

def test_d4_rolled_booking_still_fires_when_player_books_on_day_25():
    world, brief = tasks.prepare_task("invoice_mismatch")
    fork = tasks.fork(world)
    driver = tasks.make_event_driver("invoice_mismatch")
    for _ in range(25):
        if fork.done:
            break
        for action in planner.plan_day(fork):
            if action["type"] != "book_container":
                fork.apply(action)
        driver(fork)
        fork.end_day()
    assert fork.day == 25
    assert not any(b.state == "booked" for b in fork.records.all("booking")), \
        "test setup needs the player to have booked nothing before day 25"

    finished_sku, qty = next((sku, qty) for sku, qty in fork.stock["PLANT"].items()
                              if sku in ("EB-STD", "EB-PRO", "SPK-1") and qty > 0)
    result = fork.apply({"type": "book_container", "mode": "air", "lines": {finished_sku: qty}})
    assert result["ok"] if isinstance(result, dict) and "ok" in result else True

    driver(fork)
    fork.end_day()

    ev = tasks.evidence(fork, "invoice_mismatch")
    assert ev["rolled_booking_day"] == 25
    rolled = [b for b in fork.records.all("booking") if any(s == "rolled" for _, s, _ in b.history)]
    assert len(rolled) == 1, "exactly one booking should have been rolled"


def test_d4_rolled_booking_day_is_none_when_never_eligible():
    world, brief = tasks.prepare_task("invoice_mismatch")
    fork = tasks.fork(world)
    driver = tasks.make_event_driver("invoice_mismatch")
    for _ in range(45):
        if fork.done:
            break
        for action in planner.plan_day(fork):
            if action["type"] != "book_container":
                fork.apply(action)
        driver(fork)
        fork.end_day()
    ev = tasks.evidence(fork, "invoice_mismatch")
    assert ev["rolled_booking_day"] is None
    assert ev["rolled_bookings"] == []


# -- Round 2 concern 1: _force_invoice_mismatch retries until it fires -----------------

def test_round2_force_invoice_mismatch_returns_false_and_is_a_noop_with_no_inspected_po():
    world = World(1005)
    fired = tasks._force_invoice_mismatch(world)
    assert fired is False
    assert not world.records.all("invoice_in")
    assert getattr(world, "_mismatch_forced_day", None) is None


def test_round2_force_invoice_mismatch_fires_once_an_inspected_po_exists():
    world = World(1005)
    po = world.records.new("po", world.day, "inspected", supplier="S-BAT", component="BAT",
                            unit_price=10.0, shipped_qty=500, qty=500)
    fired = tasks._force_invoice_mismatch(world)
    assert fired is True
    assert world._mismatch_forced_day == world.day
    assert po.state == "invoiced"
    inv_id = po.data["invoice_id"]
    inv = world.records.get(inv_id)
    assert inv.state == "blocked"
    assert inv.data["amount"] == round(10.0 * 500 * 1.10, 2)


def test_round2_invoice_mismatch_override_is_a_retry_override_bounded_to_horizon():
    day, until_day, fn = tasks.TASKS["invoice_mismatch"]["overrides"][0]
    spec = tasks.TASKS["invoice_mismatch"]
    assert (day, until_day, fn) == (21, spec["start_day"] + spec["days"] - 1, tasks._force_invoice_mismatch)


def test_round2_invoice_mismatch_override_retries_past_day21_when_nothing_is_inspected_that_day():
    """Reproduces the exact glitch found in the invoice_mismatch revision-2 re-run
    (docs/model-findings.md section 5b): procurement's seeded POs mean *some* PO is
    normally inspected well before day 21, but nothing guarantees one is inspected
    -- as opposed to already past it, or not yet promoted to it -- at the precise
    moment the override checks on day 21 itself. Forcing that exact condition here
    (no PO in 'inspected' right when day 21's override check runs) and letting the
    simulation continue confirms the retry loop recovers on a later day instead of
    the pre-round-2 permanent no-op."""
    world, brief = tasks.prepare_task("invoice_mismatch")
    fork = tasks.fork(world)
    driver = tasks.make_event_driver("invoice_mismatch")
    for _ in range(21):
        if fork.done:
            break
        for action in planner.plan_day(fork):
            fork.apply(action)
        driver(fork)
        fork.end_day()
    assert fork.day == 21

    for po in fork.records.all("po"):
        if po.state == "inspected":
            transition(po, "invoiced", fork.day, "invoiced")
    assert not any(p.state == "inspected" for p in fork.records.all("po")), \
        "test setup needs no PO left in 'inspected' right before day 21's override check"

    driver(fork)  # day 21's check: nothing eligible -> no-op, retry continues on later days
    assert getattr(fork, "_mismatch_forced_day", None) is None
    fork.end_day()

    for _ in range(23):
        if fork.done:
            break
        for action in planner.plan_day(fork):
            fork.apply(action)
        driver(fork)
        fork.end_day()

    ev = tasks.evidence(fork, "invoice_mismatch")
    assert ev["mismatch_forced_day"] is not None and ev["mismatch_forced_day"] > 21
    assert ev["mismatched_invoices"]


def test_round2_make_event_driver_retries_stub_until_it_fires(monkeypatch):
    """Generic retry mechanism (shared by both invoice_mismatch overrides), tested
    deterministically via a stub instead of relying on real PO/booking timing."""
    calls = []

    def stub(world):
        calls.append(world.day)
        return world.day == 3

    monkeypatch.setitem(tasks.TASKS, "_round2_stub_fires", {"overrides": [(1, 5, stub)]})
    driver = tasks.make_event_driver("_round2_stub_fires")
    world = World(1005)
    for day in range(1, 6):
        world.day = day
        driver(world)
    assert calls == [1, 2, 3]  # stops retrying once it fires


def test_round2_make_event_driver_stub_never_fires_stays_none(monkeypatch):
    calls = []

    def stub(world):
        calls.append(world.day)
        return False

    monkeypatch.setitem(tasks.TASKS, "_round2_stub_never_fires", {"overrides": [(1, 5, stub)]})
    driver = tasks.make_event_driver("_round2_stub_never_fires")
    world = World(1005)
    for day in range(1, 6):
        world.day = day
        driver(world)
    assert calls == [1, 2, 3, 4, 5]  # retries through the whole window, never marks fired


# -- Round 2 concern 2: mismatched_invoices derived from state/history, not amount -----

def test_round2_mismatched_invoices_survives_dispute_resolution():
    """An invoice that was genuinely created mismatched (state 'blocked') but has since
    been disputed and resolved at -6% can end up with amount < expected*1.01 -- it must
    still count, since it is derived from history, not the post-resolution amount."""
    world, brief = tasks.prepare_task("invoice_mismatch")
    fork = tasks.fork(world)
    day = fork.day
    inv = fork.records.new("invoice_in", day, "blocked", po_id="PO-TEST", supplier="S-BAT",
                            amount=106000.0, expected=100000.0, due_day=day + 30)
    transition(inv, "disputed", day + 1, "disputed by planner")
    transition(inv, "accepted", day + 11, "dispute resolved at -6%")
    inv.data["amount"] *= 0.94
    transition(inv, "paid", day + 11, "paid")
    assert inv.data["amount"] < inv.data["expected"] * 1.01, \
        "test setup: post-resolution amount must be below the old (now-removed) threshold"

    ev = tasks.evidence(fork, "invoice_mismatch")
    assert inv.id in ev["mismatched_invoices"]


def test_round2_mismatched_invoices_excludes_never_blocked_invoice():
    world, brief = tasks.prepare_task("invoice_mismatch")
    fork = tasks.fork(world)
    day = fork.day
    inv = fork.records.new("invoice_in", day, "open", po_id="PO-TEST2", supplier="S-BAT",
                            amount=100000.0, expected=100000.0, due_day=day + 30)
    transition(inv, "accepted", day, "auto-matched: fully covered by deposit+balance")
    transition(inv, "paid", day, "paid")

    ev = tasks.evidence(fork, "invoice_mismatch")
    assert inv.id not in ev["mismatched_invoices"]


# -- SOURCE_HASH excludes api.py/artifact.py --------------------------------------------

def test_source_hash_excludes_api_and_artifact():
    names = {p.name for p in tasks._SRC}
    assert "api.py" not in names
    assert "artifact.py" not in names
    assert "world.py" in names and "records.py" in names
