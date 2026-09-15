# Kestrel tasks (Task 17)

Five named evaluation tasks live in `kestrel/agent/tasks.py`. Each task is a
starting state warmed up by the rule planner (SPEC §10), forked so every
player sees an identical, deterministic checkpoint, then run for a fixed
horizon with a small set of explicit, documented overrides applied at the
engine boundary -- never through generated prose, and never visible in the
public brief or in a run's exported JSON.

## Contracts

- `TaskSpec` (private, in `TASKS`): `version`, `seed`, `start_day`, `days`,
  `public_brief`, `overrides` (a list whose entries are either `(absolute_day,
  fn)` -- `fn` mutates `world` directly and fires exactly once, on that day,
  regardless of what it does (e.g. forcing a lane state) -- or `(absolute_day,
  until_day, fn)` -- fires `fn` once per day from `absolute_day` through
  `until_day` inclusive until `fn` returns a truthy "it fired" result (D4 fix;
  both of `invoice_mismatch`'s overrides -- the forced mismatched invoice and
  the forced rolled booking -- use this shape as of round 2; `red_sea` and
  `soc_insolvency` still use the plain one-shot shape, since their
  preconditions don't depend on planner choices). `make_event_driver`
  dispatches on `len(entry)`.
- `prepare_task(task_id) -> (world, public_brief)`: runs the rule planner
  from day 0 to `start_day`, returns that warmed-up `World` plus the public
  brief dict (`id, version, seed, start_day, days, public_brief` -- no
  overrides, no hidden fields). Fork the returned world *after* this, before
  either player acts.
- `fork(world)`: the checkpoint helper. Plain `copy.deepcopy(world)` fails
  because `World.modules`/`World.actions` hold references to imported Python
  modules, which the pickle/deepcopy protocol cannot copy. Those two
  attributes are stateless across every `World` in the process, so `fork`
  detaches them, deep-copies everything else (records, ledger, both RNG
  streams, stock, demand, conditions, calendar position), and reattaches the
  same shared references on the clone.
- `make_event_driver(task_id) -> driver(world)`: returns a function that,
  called just before `world.end_day()`, applies any override scheduled for
  `world.day` (a one-shot `(day, fn)` override) or due for a retry (a
  `(day, until_day, fn)` override still within its window and not yet
  fired). The same driver instance must be used for every day of a given
  player's run (it holds per-override "already fired" state internally), but
  a fresh driver is created per player/checkpoint via a fresh
  `make_event_driver(task_id)` call, so no state leaks between players.
- `rule_day(world, event_driver=None) -> frame`: one day of the rule
  planner, matching `kestrel/api.py`'s frame shape exactly:
  `{day, date, screens_before, actions:[{action, result}], note, report,
  screens_after, status, error}`. `build_frame(...)` is exposed separately
  so the Task 18 LLM day loop can reuse it.
- `baseline_run(task_id) -> Run`: runs a task's full horizon with the rule
  planner and returns `{schema_version, run_id, task_id, task_version,
  source_hash, player="rule", model=None, parameters, started_at,
  initial_day, requested_days, completed_days, status, usage, frames,
  records}`. `source_hash` is the first 12 hex chars of the sha256 of every
  `kestrel/*.py` source file the simulation/agent pipeline actually imports,
  concatenated in sorted order -- `kestrel/api.py` and `kestrel/artifact.py`
  are excluded because neither is imported by `kestrel.agent`/`tasks.py`'s
  own 16 engine modules (see the comment next to `SOURCE_HASH` in
  `kestrel/agent/tasks.py` for the exact list); this keeps unrelated,
  concurrent frontend/artifact work from changing `source_hash` (D-fix,
  docs/model-findings.md "SOURCE_HASH differs across tasks").
- `evidence(world, task_id) -> dict`: task-specific public record IDs and
  metrics, read only from `world.ledger`/`world.records`/`world.news` (and,
  for `invoice_mismatch`'s `rolled_booking_day`/`mismatch_forced_day`, plain
  non-hidden attributes `_force_rolled_booking`/`_force_invoice_mismatch` set
  on `world` themselves the day each fires). `invoice_mismatch`'s
  `mismatched_invoices` is derived from each `invoice_in`'s state/history
  (ever `"blocked"` or `"disputed"`), not its current `amount` field, since
  dispute resolution mutates `amount` in place and can push a genuinely
  mismatched, already-resolved invoice's amount back under any amount-based
  threshold (round-2 fix). Persisted into `run.json["evidence"]` by both
  `runner.py::_base_result` and this module's `baseline_run` at every write
  (D2 fix), so it is readable from a finished run's own `run.json` without
  re-executing the simulation.
- `save_checkpoint(path)` / `load_checkpoint(path)`: pickle, for trusted
  local files only (never accept an uploaded pickle). Uses the same
  detach/reattach trick as `fork` for the module references.

## The five tasks

| id | seed | start_day | days | override day(s) + what fires | evidence fields |
|---|---|---|---|---|---|
| `red_sea` | 1001 | 0 | 45 | day 3: `world.cond._force_lane("diverted", day)` | `lane_news` (public news items, kind `"lane"`, body mentions the Cape of Good Hope reroute), `demurrage_total` |
| `cny_prebuild` | 1002 | 0 | 60 | none (Chinese New Year falls inside the window on the calendar alone, SPEC §4) | `ship_slipped_pos` (PO IDs whose history records a "China capacity" ship-day slip) |
| `soc_insolvency` | 1003 | 60 | 45 | day 65: `world.cond._set_health("S-SOC", "insolvent", day)` | `cancelled_soc_pos` (S-SOC PO IDs cancelled for insolvency), `scorecard` (S-SOC's latest monthly scorecard) |
| `black_friday` | 1004 | day of 2026-10-20 | 45 | none (Black Friday, 23-29 Nov, falls inside the window) | `black_friday_week_qty` vs `baseline_week_qty` (customer order quantity, 9-15 Nov) |
| `invoice_mismatch` | 1005 | 0 | 45 | days 21-44 (retried daily until it fires, D4 fix): creates a mismatched `invoice_in` on a PO that has just reached `inspected` (mirrors `procurement._invoice`'s own mismatch branch, forced instead of left to its 8% draw); days 21-44 (retried daily until it fires, D4 fix): force-rolls exactly one `booked` booking -- the earliest by id -- through `cut_off` then `rolled` (mirrors `logistics._load`'s own roll branch) | `mismatched_invoices` (invoice IDs ever `blocked`/`disputed` in their history), `rolled_bookings` (booking IDs whose history contains a `rolled` transition), `rolled_booking_day` / `mismatch_forced_day` (absolute day each forced override actually fired, or `None` if no eligible target ever existed in its window) |

### Why `invoice_mismatch`'s overrides construct records instead of editing one

Under the engine's normal dynamics, a correctly-priced invoice is created and
immediately auto-settled (`due <= 0`) in the same call, and an organically
mismatched invoice starts life already `blocked` -- so a persisting `"open"`
invoice with a resolvable mismatch essentially never exists to edit in place.
The override instead pre-empts `procurement._invoice`'s own logic for one PO
that has just reached `inspected` (before the day's `advance()` would invoice
it correctly), creating the same `invoice_in` record shape with a forced
10% overprice and firing the same public exception the organic path would
fire. This is the smallest boundary-level substitute for "change an open
invoice's amount" that actually produces an observable, disputable event; it
uses only public engine primitives (`records.new`, `records.transition`,
`world.exception`) already used by the real invoicing code, not generated
prose.

### Indistinguishability from an organic event (fix round 1)

Both `_force_invoice_mismatch` and `_force_rolled_booking` pass `transition()`
and `world.exception()` the exact same detail/message strings the organic
code paths use for the same transition -- `"invoiced"` and
`f"invoice {id} mismatches PO {id}: {amount:.2f} vs {expected:.2f}"` from
`procurement._invoice`; `"cut-off reached"`, `"rolled to next sailing"`, and
`f"booking {id} rolled; new cutoff day {day}"` from `logistics._load` -- with
no "(scenario override)" suffix or similar tell. `world.screens()` therefore
renders a forced event exactly as it would render an organic one; a player
reading exceptions/history cannot distinguish the two by text.

`_force_rolled_booking` selects exactly one booking to cut off and roll: the
earliest by `id` among those currently in state `booked`. It does not touch
any other open booking, even if several are `booked` on the override day.

### Reproducibility fix: the rolled-booking override retries until it fires (D4)

A live model run (Task 19) found that a player who has not booked any freight
by day 21 leaves `_force_rolled_booking` nothing to roll that day, so the
event -- documented as "reproducible" -- silently never happened for that
player, while the rule baseline (which always has a booking by day 21) saw
it every time. `make_event_driver` now retries `_force_rolled_booking` once
per day from day 21 through the task's last day (44) until it finds an
eligible `booked` booking, instead of checking only day 21. `evidence()`'s
`rolled_booking_day` records which day it actually fired, or `None` if the
player never had an eligible booking in the whole window. This documented,
at the time, that it did not change `_force_invoice_mismatch`, which fired
only on day 21 and appeared not to have this problem (a PO reaching
`inspected` does not depend on planner choices the way freight booking
timing does) -- **superseded by round 2 below**, which found that claim was
narrower than it looked.

### Round 2: `_force_invoice_mismatch` gets the same retry fix, and `mismatched_invoices` is made resolution-proof

The `invoice_mismatch` revision-2 re-run (docs/model-findings.md section 5b)
found that `_force_invoice_mismatch` *can* hit the same problem as the
rolled-booking override, just through a narrower door: reaching `inspected`
doesn't depend on planner choices, but the override's day-21 check runs
*before* that day's own procurement `advance()` step (which is what promotes
a PO into `inspected` or out of it), so a PO that is inspected exactly on day
21 is not yet visible to the check, and one that was inspected earlier may
already have advanced past it by day 21 -- a purely time-of-check gap, no
player action required. `_force_invoice_mismatch` now uses the identical
`(day, until_day, fn)` retry shape as `_force_rolled_booking`: it retries
daily from day 21 through day 44 until a PO is found in state `inspected`,
returns `True`/sets `world._mismatch_forced_day` when it fires, and
`evidence()`'s new `mismatch_forced_day` field records which day (or `None`).

Separately, `evidence()`'s old `mismatched_invoices` filter
(`amount > expected * 1.01`) read the record's *current* `amount`, which
`procurement._settle` mutates in place on dispute resolution
(`amount *= 0.94`). For an organically-mismatched invoice
(`amount = expected * 1.06` at creation), resolution leaves
`amount = expected * 1.06 * 0.94 = expected * 0.9964` -- *below* the old
threshold, so a genuinely mismatched invoice silently dropped out of the
list once resolved. `mismatched_invoices` is now derived from state/history
instead: any `invoice_in` that was ever in state `"blocked"` or `"disputed"`
counts, which is resolution-proof and, per `LEGAL["invoice_in"]`, also a
complete proxy for "was created mismatched" (a correctly-priced invoice is
created `"open"` and settles immediately; only a mismatched one is ever
created `"blocked"`, and `"disputed"` is reachable only from `"blocked"`).

## Tests

`tests/test_tasks.py` (12 tests): five tasks defined with valid fields;
`prepare_task` returns a checkpoint plus a public brief with no leaked
overrides; two forks of the same checkpoint yield equal `screens()`/`export()`;
identical actions replayed from a shared checkpoint (via `rule_day`) stay
byte-identical; a fork given one extra deliberate action (a markdown)
physically diverges from its sibling; each of the five tasks, run for its
full horizon with `checks.verify` after every day, produces its scheduled
event visibly in public records/news; `baseline_run` matches the `Run`
contract; no hidden condition field leaks into a run's JSON.
