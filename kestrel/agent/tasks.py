"""Task scenarios, checkpoints, and rule-planner runs (Task 17, SPEC §11).

Each task is a warmed-up starting state plus a fixed horizon and a small set
of explicit, documented overrides applied at the engine boundary -- never
through generated prose, never visible in a public brief or run export.
"""
import copy
import hashlib
import pickle
from datetime import date
from pathlib import Path

from .. import calendar as cal
from .. import distribution, fulfilment, logistics, plant, procurement
from .. import planner
from ..records import transition
from ..screens import record_view
from ..world import World

# Only the modules the simulation/agent pipeline actually imports go into SOURCE_HASH: the
# 16 engine modules (__init__.py, calendar.py, network.py, records.py, demand.py, aql.py,
# conditions.py, fulfilment.py, logistics.py, procurement.py, plant.py, screens.py, planner.py,
# finance.py, distribution.py, checks.py, world.py). kestrel/api.py (the HTTP frontend for the
# operations desk) and kestrel/artifact.py (the offline-demo exporter) are excluded: neither is
# imported by kestrel.agent or by any of the 16 modules above, so a change to either changes
# SOURCE_HASH without changing simulation behavior, which previously made cross-run source_hash
# comparisons misleading (docs/model-findings.md, "SOURCE_HASH differs across tasks").
_SRC_EXCLUDE = {"api.py", "artifact.py"}
_SRC = sorted(p for p in Path(__file__).resolve().parents[1].glob("*.py") if p.name not in _SRC_EXCLUDE)
SOURCE_HASH = hashlib.sha256(b"".join(p.read_bytes() for p in _SRC)).hexdigest()[:12]

# Public run fields served by the API and embedded in the artifact. Everything
# else in run.json (private overrides, request bodies) stays on disk.
PUBLIC_RUN_FIELDS = ("schema_version", "run_id", "task_id", "task_version", "source_hash",
                     "player", "model", "parameters", "started_at", "initial_day",
                     "requested_days", "completed_days", "status", "usage", "evidence",
                     "frames", "records")

_MODULES = [procurement, logistics, plant, distribution, fulfilment]


def fork(world):
    """copy.deepcopy(world) directly fails: World.modules/actions hold references to
    imported Python modules and module-to-function tuples, which pickle (and hence
    deepcopy, which uses the same __reduce_ex__ protocol) cannot copy. Those two
    attributes are stateless -- the same five modules for every World in this process
    -- so it is correct to detach them, deep-copy everything else, and reattach the
    original (shared, stateless) references on the clone. This is the small checkpoint
    helper the brief allows; no persistence framework."""
    modules, actions = world.modules, world.actions
    world.modules = world.actions = None
    try:
        clone = copy.deepcopy(world)
    finally:
        world.modules, world.actions = modules, actions
    clone.modules, clone.actions = modules, actions
    return clone


# -- scenario overrides: small, explicit engine-boundary hooks --------------

def _force_red_sea_diversion(world):
    world.cond._force_lane("diverted", world.day)


def _force_soc_insolvent(world):
    world.cond._set_health("S-SOC", "insolvent", world.day)


def _force_invoice_mismatch(world) -> bool:
    """Under normal dynamics an invoice that matches its PO settles the same day it is
    created (deposit+balance already cover it), so a genuinely open, disputable mismatch
    only exists when procurement._invoice's random 8% draw happens to hit. To make the
    event reproducible we pre-empt that same step for one PO that has reached 'inspected'
    but has no invoice yet, creating the mismatched invoice_in ourselves exactly as
    procurement._invoice would on a mismatch draw, then closing the PO's own path to it.
    Detail/exception text is byte-identical to procurement._invoice's own mismatch branch
    (kestrel/procurement.py) so the forced event is indistinguishable from an organic one
    in world.screens().

    Round-2 fix: a player whose own PO/procurement pacing leaves no PO in state 'inspected'
    on the scheduled override day previously made this a silent, permanent no-op (found
    during the invoice_mismatch revision-2 re-run, docs/model-findings.md section 5b) --
    returns False so the caller (make_event_driver's retry loop) keeps trying on subsequent
    days instead. Returns True the day it actually fires, and records which day on `world`
    for evidence()."""
    po = next((p for p in world.records.open("po") if p.state == "inspected"), None)
    if po is None:
        return False
    expected = po.data["unit_price"] * po.data["shipped_qty"]
    amount = round(expected * 1.10, 2)
    inv = world.records.new("invoice_in", world.day, "blocked", po_id=po.id, supplier=po.data["supplier"],
                             amount=amount, expected=expected, due_day=world.day + 30)
    po.data["invoice_id"] = inv.id
    transition(po, "invoiced", world.day, "invoiced")
    world.exception("invoice", inv.id, f"invoice {inv.id} mismatches PO {po.id}: {amount:.2f} vs {expected:.2f}")
    world._mismatch_forced_day = world.day
    return True


def _force_rolled_booking(world) -> bool:
    """Cuts off and rolls exactly one booking: the earliest by id among those currently
    'booked' (deterministic given a fixed seed/planner). Detail/exception text is
    byte-identical to logistics._load's own cut-off/roll branches (kestrel/logistics.py)
    so the forced event is indistinguishable from an organic one in world.screens().

    D4 fix: a player who has not booked any freight yet by the scheduled override day has
    no 'booked' booking to roll, so this is a no-op that day -- returns False so the caller
    (make_event_driver's retry loop) keeps trying on subsequent days instead of silently
    treating the event as having occurred (docs/model-findings.md D4). Returns True the day
    it actually fires, and records which day and booking on `world` for evidence()."""
    booked = sorted((b for b in world.records.open("booking") if b.state == "booked"), key=lambda b: b.id)
    if not booked:
        return False
    bk = booked[0]
    transition(bk, "cut_off", world.day, "cut-off reached")
    bk.data["cutoff_day"] += 7
    transition(bk, "rolled", world.day, "rolled to next sailing")
    world.exception("booking", bk.id, f"booking {bk.id} rolled; new cutoff day {bk.data['cutoff_day']}")
    world._rolled_booking_forced_day = world.day
    return True


# -- the five tasks (SPEC §11) -----------------------------------------------

TASKS = {
    "red_sea": {
        "version": 1, "seed": 1001, "start_day": 0, "days": 45,
        "public_brief": "A carrier alliance notice may affect Asia-Europe lanes early in the run. "
                         "Protect regional service and Rotterdam demurrage.",
        "overrides": [(3, _force_red_sea_diversion)],
    },
    "cny_prebuild": {
        "version": 1, "seed": 1002, "start_day": 0, "days": 60,
        "public_brief": "Chinese New Year falls within the horizon: supplier and plant capacity "
                         "ramps down before the holiday and back up after. Build ahead of it.",
        "overrides": [],
    },
    "soc_insolvency": {
        "version": 1, "seed": 1003, "start_day": 60, "days": 45,
        "public_brief": "Watch the S-SOC scorecard closely; audio SoC supply has looked shaky.",
        "overrides": [(65, _force_soc_insolvent)],
    },
    "black_friday": {
        "version": 1, "seed": 1004, "start_day": cal.to_day(date(2026, 10, 20)), "days": 45,
        "public_brief": "Black Friday is coming. Hold the right stock for the right customer "
                         "and avoid chargebacks.",
        "overrides": [],
    },
    "invoice_mismatch": {
        "version": 1, "seed": 1005, "start_day": 0, "days": 45,
        "public_brief": "A busy week ahead: clear the inbox without paying a wrong invoice "
                         "or missing a rolled booking.",
        # Both entries are filled in below (D4 fix, round 1 for the booking one, round 2 for
        # the invoice one) as (day, until_day, fn) retry overrides instead of plain (day, fn)
        # one-shots -- each needs the task's own start_day/days to compute its retry deadline.
        "overrides": [None, None],
    },
}

# D4 (docs/model-findings.md): both invoice_mismatch overrides silently no-op, permanently,
# if their precondition (a PO in state "inspected" / a booking in state "booked") does not
# hold on their scheduled day -- reliable for the rule baseline (which always satisfies both
# by day 21) but not guaranteed for a model player whose own procurement/freight pacing
# differs. Round 1 fixed the booking override; round 2 (found during the revision-2 re-run,
# docs/model-findings.md section 5b) applies the identical fix to the invoice override. Both
# now retry daily from day 21 through the last day of the task's horizon (inclusive) until
# their precondition holds.
_im = TASKS["invoice_mismatch"]
_im["overrides"][0] = (21, _im["start_day"] + _im["days"] - 1, _force_invoice_mismatch)
_im["overrides"][1] = (21, _im["start_day"] + _im["days"] - 1, _force_rolled_booking)
del _im


def task_public_brief(task_id: str) -> dict:
    spec = TASKS[task_id]
    return {"id": task_id, "version": spec["version"], "seed": spec["seed"],
            "start_day": spec["start_day"], "days": spec["days"], "public_brief": spec["public_brief"]}


def prepare_task(task_id: str):
    """Warm up the starting state with the rule planner and return (checkpoint_world, public_brief).
    Fork the returned world (copy.deepcopy) after this, before either player acts."""
    spec = TASKS[task_id]
    world = World(spec["seed"])
    for _ in range(spec["start_day"]):
        if world.done:
            break
        for action in planner.plan_day(world):
            world.apply(action)
        world.end_day()
    return world, task_public_brief(task_id)


def make_event_driver(task_id: str):
    """Return a driver applying task_id's overrides on their scheduled absolute day.
    Call it just before world.end_day(); the same driver applies to every player.

    Two override shapes: `(day, fn)` fires fn exactly once, on that absolute day, regardless
    of what fn does (the original three tasks' overrides -- unchanged by D4). `(day, until_day,
    fn)` (D4 fix, currently only invoice_mismatch's rolled-booking override) retries fn once
    per day from `day` through `until_day` inclusive until fn returns a truthy "it fired"
    result, then stops -- so it still fires for a player whose own decisions leave no eligible
    target on the originally-scheduled day."""
    overrides = TASKS[task_id]["overrides"]
    fired = [False] * len(overrides)

    def driver(world):
        for i, entry in enumerate(overrides):
            if len(entry) == 2:
                day, fn = entry
                if world.day == day:
                    fn(world)
            else:
                day, until_day, fn = entry
                if not fired[i] and day <= world.day <= until_day:
                    fired[i] = bool(fn(world))
    return driver


# -- local, trusted checkpoint files (never accept uploaded pickle) --------

def save_checkpoint(world, path):
    modules, actions = world.modules, world.actions
    world.modules = world.actions = None
    try:
        Path(path).write_bytes(pickle.dumps(world))
    finally:
        world.modules, world.actions = modules, actions


def load_checkpoint(path):
    world = pickle.loads(Path(path).read_bytes())
    world.modules = list(_MODULES)
    world.actions = {k: (m, f) for m in world.modules for k, f in m.ACTIONS.items()}
    return world


# -- frame / run-day (rule-planner variant; the LLM variant is Task 18) ----

def build_frame(day, date_str, screens_before, actions, results, note, report, screens_after, status, error):
    return {"day": day, "date": date_str, "screens_before": screens_before,
            "actions": [{"action": a, "result": r} for a, r in zip(actions, results)],
            "note": note, "report": report, "screens_after": screens_after,
            "status": status, "error": error}


def rule_day(world, event_driver=None) -> dict:
    """Run one day with the rule planner. Applies event_driver just before end_day()."""
    if world.done:
        return build_frame(world.day, cal.to_date(world.day).isoformat(), None, [], [],
                            "", None, None, "incomplete", "episode finished")
    screens_before = world.screens()
    actions = planner.plan_day(world)
    results = [world.apply(a) for a in actions]
    if event_driver is not None:
        event_driver(world)
    note = planner.note(world)
    report = world.end_day()
    screens_after = world.screens()
    return build_frame(report["day"], report["date"], screens_before, actions, results,
                        note, report, screens_after, "complete", None)


# -- baseline (rule-planner) runs and task-specific evidence ----------------

def baseline_run(task_id: str) -> dict:
    spec = TASKS[task_id]
    world, brief = prepare_task(task_id)
    driver = make_event_driver(task_id)
    frames = []
    for _ in range(spec["days"]):
        if world.done:
            break
        frames.append(rule_day(world, driver))
    return {
        "schema_version": 1, "run_id": f"{task_id}-rule-{spec['seed']}", "task_id": task_id,
        "task_version": spec["version"], "source_hash": SOURCE_HASH, "player": "rule", "model": None,
        "parameters": {}, "started_at": None, "initial_day": brief["start_day"],
        "requested_days": spec["days"], "completed_days": len(frames),
        "status": "complete" if len(frames) == spec["days"] else "incomplete",
        "usage": {}, "frames": frames,
        "records": {rid: record_view(world.records.get(rid)) for rid in world.records.ids()},
        # D2: see kestrel/agent/runner.py::_base_result's identical field for why.
        "evidence": evidence(world, task_id),
    }


def evidence(world, task_id: str) -> dict:
    """Task-specific public record IDs and metrics. Numbers come from world.ledger/records only."""
    if task_id == "red_sea":
        lane_news = [n for n in world.news if n.get("kind") == "lane"]
        return {"lane_news": lane_news, "demurrage_total": round(-world.ledger.total("demurrage"), 2)}
    if task_id == "cny_prebuild":
        slipped = [po.id for po in world.records.all("po")
                   if any("China capacity" in note for _, _, note in po.history)]
        return {"ship_slipped_pos": slipped}
    if task_id == "soc_insolvency":
        cancelled = [po.id for po in world.records.all("po")
                     if po.data["supplier"] == "S-SOC" and po.state == "cancelled"]
        return {"cancelled_soc_pos": cancelled, "scorecard": world.scorecards.get("S-SOC")}
    if task_id == "black_friday":
        bf_start, bf_end = cal.to_day(date(2026, 11, 23)), cal.to_day(date(2026, 11, 29))
        base_start, base_end = cal.to_day(date(2026, 11, 9)), cal.to_day(date(2026, 11, 15))
        orders = world.records.all("order")
        bf_qty = sum(o.data["qty"] for o in orders if bf_start <= o.created_day <= bf_end)
        base_qty = sum(o.data["qty"] for o in orders if base_start <= o.created_day <= base_end)
        return {"black_friday_week_qty": bf_qty, "baseline_week_qty": base_qty}
    if task_id == "invoice_mismatch":
        # Round 2 fix: derived from state/history, not the current `amount` field. `amount`
        # only ever exceeds `expected*1.01` at creation for a mismatched invoice (both the
        # organic 8%-draw and the forced path always create it directly in state "blocked";
        # a correctly-priced invoice is created "open" and never becomes "blocked"), but
        # `_settle`'s dispute resolution later multiplies `amount` by 0.94 in place, which can
        # push a resolved mismatch's *current* amount back below the old amount-based threshold
        # (1.06*0.94=0.9964 for an organic mismatch) -- silently dropping it from this list
        # despite it having genuinely been a mismatch (found during the invoice_mismatch
        # revision-2 re-run, docs/model-findings.md section 5b). "Ever blocked or disputed"
        # is a full, resolution-proof proxy for "was created mismatched" given the engine's
        # own transitions (LEGAL["invoice_in"] only reaches "disputed" via "blocked").
        mismatched = [i.id for i in world.records.all("invoice_in")
                      if any(state in ("blocked", "disputed") for _, state, _ in i.history)]
        rolled = [b.id for b in world.records.all("booking") if any(state == "rolled" for _, state, _ in b.history)]
        # D4: rolled_booking_day/mismatch_forced_day are the absolute day the corresponding
        # _force_* override actually fired (set on `world` by the override itself), or None if
        # it never found an eligible target within its retry window -- distinguishes "the
        # forced event fired late" from "the list is non-empty only because of an organic
        # event" (docs/model-findings.md D4).
        return {"mismatched_invoices": mismatched, "rolled_bookings": rolled,
                "rolled_booking_day": getattr(world, "_rolled_booking_forced_day", None),
                "mismatch_forced_day": getattr(world, "_mismatch_forced_day", None)}
    raise ValueError(f"unknown task {task_id!r}")
