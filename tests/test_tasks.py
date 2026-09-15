"""Task 17: task scenarios, checkpoints, and rule-planner baseline runs."""
import json

from kestrel import checks
from kestrel.agent import tasks


TASK_IDS = ("red_sea", "cny_prebuild", "soc_insolvency", "black_friday", "invoice_mismatch")


def test_five_tasks_defined():
    assert set(tasks.TASKS) == set(TASK_IDS)
    for task_id, spec in tasks.TASKS.items():
        assert 30 <= spec["days"] <= 60, task_id
        assert isinstance(spec["seed"], int)
        assert isinstance(spec["start_day"], int)
        assert isinstance(spec["public_brief"], str) and spec["public_brief"]


def test_prepare_task_returns_checkpoint_and_public_brief():
    world, brief = tasks.prepare_task("red_sea")
    assert world.day == tasks.TASKS["red_sea"]["start_day"]
    assert brief == {
        "id": "red_sea", "version": tasks.TASKS["red_sea"]["version"],
        "seed": tasks.TASKS["red_sea"]["seed"], "start_day": tasks.TASKS["red_sea"]["start_day"],
        "days": tasks.TASKS["red_sea"]["days"], "public_brief": tasks.TASKS["red_sea"]["public_brief"],
    }
    assert "overrides" not in brief  # never leaked to the public brief


def test_checkpoint_fork_gives_equal_starting_screens():
    world, _ = tasks.prepare_task("soc_insolvency")
    fork_a, fork_b = tasks.fork(world), tasks.fork(world)
    assert fork_a.screens() == fork_b.screens()
    assert fork_a.export() == fork_b.export()


def test_same_actions_replay_deterministically():
    world, _ = tasks.prepare_task("invoice_mismatch")
    fork_a, fork_b = tasks.fork(world), tasks.fork(world)
    driver = tasks.make_event_driver("invoice_mismatch")
    for _ in range(10):
        tasks.rule_day(fork_a, driver)
        tasks.rule_day(fork_b, driver)
    assert fork_a.export() == fork_b.export()


def test_different_actions_cause_physical_divergence():
    world, _ = tasks.prepare_task("black_friday")
    fork_a, fork_b = tasks.fork(world), tasks.fork(world)
    # Fork B takes an extra, deliberate action fork A never sees: a deep markdown on one SKU.
    result = fork_b.apply({"type": "markdown", "sku": "EB-STD", "percent": 40})
    assert result["ok"], result
    driver = tasks.make_event_driver("black_friday")
    for _ in range(15):
        tasks.rule_day(fork_a, driver)
        tasks.rule_day(fork_b, driver)
    assert fork_a.export() != fork_b.export()
    assert fork_a.markdown != fork_b.markdown


def _run_full_horizon(task_id):
    world, brief = tasks.prepare_task(task_id)
    driver = tasks.make_event_driver(task_id)
    for _ in range(brief["days"]):
        if world.done:
            break
        tasks.rule_day(world, driver)
        checks.verify(world)
    return world


def test_red_sea_diversion_event_occurs():
    world = _run_full_horizon("red_sea")
    ev = tasks.evidence(world, "red_sea")
    assert ev["lane_news"], "expected a lane-disruption news item"
    assert any("Cape" in n["body"] for n in ev["lane_news"])


def test_cny_prebuild_capacity_holiday_hits_shipments():
    world = _run_full_horizon("cny_prebuild")
    ev = tasks.evidence(world, "cny_prebuild")
    assert ev["ship_slipped_pos"], "expected at least one PO whose ship day slipped for CNY capacity"


def test_soc_insolvency_cancels_open_pos():
    world = _run_full_horizon("soc_insolvency")
    ev = tasks.evidence(world, "soc_insolvency")
    assert ev["cancelled_soc_pos"], "expected S-SOC insolvency to cancel at least one open PO"
    assert any(e["kind"] == "supplier" for e in world.exceptions)


def test_black_friday_orders_exceed_baseline_week():
    world = _run_full_horizon("black_friday")
    ev = tasks.evidence(world, "black_friday")
    assert ev["black_friday_week_qty"] > ev["baseline_week_qty"]


def test_invoice_mismatch_and_rolled_booking_both_occur():
    world = _run_full_horizon("invoice_mismatch")
    ev = tasks.evidence(world, "invoice_mismatch")
    assert ev["mismatched_invoices"], "expected a forced invoice mismatch to be resolved"
    assert ev["rolled_bookings"], "expected a booking to be forced into the rolled state"


def test_forced_events_are_indistinguishable_from_organic_ones_in_screens():
    """The two invoice_mismatch overrides must not leak the fact that they are
    scenario overrides into anything a player/model can read."""
    world, brief = tasks.prepare_task("invoice_mismatch")
    driver = tasks.make_event_driver("invoice_mismatch")
    override_day = tasks.TASKS["invoice_mismatch"]["overrides"][0][0]
    for _ in range(brief["days"]):
        if world.done:
            break
        tasks.rule_day(world, driver)
        if world.day > override_day:
            blob = json.dumps(world.screens()).lower()
            assert "scenario" not in blob and "override" not in blob


def test_force_rolled_booking_touches_exactly_one_booking():
    """_force_rolled_booking must cut off/roll only the earliest-by-id currently-booked
    booking, leaving any other concurrently booked booking (not otherwise due for
    organic cut-off that day) untouched."""
    world, _ = tasks.prepare_task("invoice_mismatch")
    driver = tasks.make_event_driver("invoice_mismatch")
    override_day = tasks.TASKS["invoice_mismatch"]["overrides"][0][0]
    for _ in range(override_day):
        tasks.rule_day(world, driver)
    before_booked = sorted((b for b in world.records.open("booking") if b.state == "booked"), key=lambda b: b.id)
    assert len(before_booked) >= 2, "scenario needs >=2 concurrently booked bookings to test scope"
    target, untouched = before_booked[0], before_booked[1:]
    for b in untouched:
        assert b.data["cutoff_day"] > world.day, "test needs an untouched candidate not organically due today"
    tasks.rule_day(world, driver)
    assert any(state == "rolled" for _, state, _ in target.history)
    for b in untouched:
        assert b.state == "booked"


def test_baseline_run_matches_run_contract():
    run = tasks.baseline_run("red_sea")
    for key in ("schema_version", "run_id", "task_id", "task_version", "source_hash", "player",
                "model", "parameters", "started_at", "initial_day", "requested_days",
                "completed_days", "status", "usage", "frames", "records"):
        assert key in run, key
    assert run["player"] == "rule"
    assert run["model"] is None
    assert run["task_id"] == "red_sea"
    assert run["completed_days"] == run["requested_days"] == tasks.TASKS["red_sea"]["days"]
    assert len(run["frames"]) == run["completed_days"]
    frame = run["frames"][0]
    for key in ("day", "date", "screens_before", "actions", "note", "report", "screens_after", "status", "error"):
        assert key in frame, key
    assert frame["status"] == "complete" and frame["error"] is None
    for entry in frame["actions"]:
        assert set(entry) == {"action", "result"}


def test_no_hidden_state_in_public_brief_or_run():
    _, brief = tasks.prepare_task("soc_insolvency")
    assert "insolvent" not in str(brief)
    run = tasks.baseline_run("soc_insolvency")
    blob = json.dumps(run, default=str)
    assert "supplier_health" not in blob and "rate_regime" not in blob
