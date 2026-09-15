# Kestrel Task 19 — live model run findings

**Revision note (2026-09-15, added after the scoped defect-fix pass).**
Sections 1-5 (`red_sea`, `cny_prebuild`, `soc_insolvency`, `black_friday`, and
the original `invoice_mismatch`) are **revision 1**: they ran before any of
this document's own "Defects for scoped fix" (D1-D4) were fixed, and in
particular D3 (`kestrel/records.py`'s `asn`/`receipt` kinds had no closed
state, so `Records.open()` returned every such record ever created) means
every `get_screen("records")` payload size and prompt-token/cost number
quoted in sections 1-5 is inflated by an unbounded, ever-growing `asn`/
`receipt` bucket that a fixed engine would not have produced — this does not
change what those runs' models actually decided, only how large their own
tool-result payloads were. Those five sections and their runs
(`runs/<task>/<player>/`, `runs/curated/<task>/<player>/`) are preserved
exactly as originally written and are never edited here. After D1-D4 were
fixed (`kestrel/records.py`, `kestrel/agent/tools.py`, `kestrel/agent/
runner.py`/`tasks.py`; see `.superpowers/sdd/2026-09-15-kestrel-world/
task-19-fix-report.md` for the per-defect change), `invoice_mismatch` alone
was re-run against the fixed code; its original runs were moved intact to
`runs/invoice_mismatch_rev1/` and `runs/curated/invoice_mismatch_rev1/`, and
the new runs lived at the original `runs/invoice_mismatch/` and
`runs/curated/invoice_mismatch/` paths as **revision 2** (section 5b).
Revision 2's own re-run then surfaced two further concerns (documented at
the end of section 5b's text): `_force_invoice_mismatch` could hit the exact
same "no eligible target at the precise moment the override checks" problem
`_force_rolled_booking` had, and `evidence()["mismatched_invoices"]` could
silently drop a genuinely mismatched invoice once dispute resolution mutated
its `amount` field. Both were fixed in a second round (same `(day,
until_day, fn)` retry mechanism applied to `_force_invoice_mismatch`, plus
`mismatched_invoices` redefined from record state/history instead of the
current `amount`); revision 2's runs were then moved intact to
`runs/invoice_mismatch_rev2/` and `runs/curated/invoice_mismatch_rev2/`, and
**revision 3** (section 5c) was run against this second-round fix, again at
the original `runs/invoice_mismatch/`/`runs/curated/invoice_mismatch/`
paths. Section 5 is revision 1, section 5b is revision 2, **section 5c is
revision 3** -- each preserved exactly as originally written; none are
number-for-number comparable across revisions because the code, not just
the RNG draw, differs each time.

Model under test: `openai/gpt-5.6-luna` via OpenRouter (player "luna" in
`kestrel/agent/runner.py`). Baseline: the rule planner ("rule" player), same
task/seed/checkpoint. All runs executed live against the real API on
2026-09-15; no unit-test proxy was used for any claim below. `source_hash` is
the first 12 hex chars of the sha256 over every `kestrel/*.py` file
(`kestrel/agent/tasks.py::SOURCE_HASH`); it is recorded per run in
`run.json["source_hash"]` and did not change across any of the runs in this
document (no engine defect fix was applied — see "Defects for scoped fix").

Curated runs: `runs/curated/<task>/<player>/run.json` (frames with
`screens_before`/`screens_after` intact) and, for luna, a stripped
`transcript.jsonl` (assistant `content`/`tool_calls` and any HTTP error per
call; the full per-call request message array is dropped because it just
repeats prior turns). Full originals with request bodies are left untouched
under `runs/<task>/<player>/`.

### Concern: `source_hash` differs across tasks (not within a task)
Each task's own `run.json["source_hash"]` is identical between its luna and
rule run (both run back-to-back in the same source state, so every
luna-vs-rule comparison in this document is apples-to-apples). But the five
tasks were not all run against byte-identical `kestrel/*.py` source:
`red_sea 30473354b830`, `cny_prebuild 59fd455981a6`, `soc_insolvency
82a9d5008b17`, `black_friday 2ca32544270d`, `invoice_mismatch 86ae5c3f01bd`
(all read from each task's own `run.json`). `SOURCE_HASH`
(`kestrel/agent/tasks.py:20-21`) hashes every file in `kestrel/*.py`
indiscriminately, including files the agent/task pipeline never imports
(`kestrel/api.py`, `kestrel/artifact.py`). Checked via `ls -la --time-style=full-iso
kestrel/*.py`: every file the simulation/agent pipeline actually uses
(`calendar.py, network.py, records.py, demand.py, aql.py, conditions.py,
fulfilment.py, logistics.py, procurement.py, plant.py, screens.py,
planner.py, finance.py, distribution.py, checks.py, world.py`) carries a
modification time between 08:15 and 11:54 UTC on 2026-09-15, before this
document's first run started (red_sea, ~12:15 UTC); only `kestrel/api.py`
(12:49 UTC) and the newly-created `kestrel/artifact.py` (13:24 UTC) — both
unused by `kestrel.agent`/`kestrel.agent.tasks`/the five engine modules
above — changed during this session, evidently from other, unrelated work
proceeding concurrently in this repo. This explains the differing
`source_hash` values without evidence that the simulation behavior differed
across tasks, but it is recorded here as a genuine limitation on this
document's cross-task comparisons (e.g. "cny_prebuild underperforms
soc_insolvency"-style claims are not made in this document precisely
because of this; only within-task luna-vs-rule comparisons and per-task
tool/model failure findings are drawn). Each task's exact `source_hash` is
in its `run.json` and reproduced in that task's section below for the
record.

---

## 1. red_sea (seed 1001, start_day 0, days 45)

### Status / usage (verbatim from `runs/red_sea/luna/run.json`)
- luna: `status="complete"`, `completed_days=45/45`, `usage={"prompt_tokens": 6932620, "completion_tokens": 25141, "total_tokens": 6957761, "cost": 0.48750008000000006, "is_byok": 0}`. No API errors (0 of 111 HTTP calls in `transcript.jsonl` carried an `error`; max 4 calls/day, cap is 40/day).
- rule: `status="complete"`, `completed_days=45/45`, `usage={}` (rule player makes no HTTP calls).

### Evidence table (`tasks.evidence`, red_sea = `lane_news`, `demurrage_total`)

| | luna | rule |
|---|---|---|
| lane news surfaced | day 6 news item, `kind="lane"`, `"Asia-Europe services rerouted via the Cape of Good Hope"`, `"Transit times extend by 10-14 days on the Cape of Good Hope route; war-risk surcharge applies."` (first appears in `screens_before.news` on day 7's opening message) | same public news stream (task-level, player-independent) |
| demurrage_total | `finance.pnl.demurrage = 0` at day 44 | `finance.pnl.demurrage = 0` at day 44 |
| operating_result (day 44) | 1,857,757.10 | 1,804,464.34 |
| chargebacks (day 44) | -3,146.32 | -414.74 |
| freight (day 44) | -16,380.00 | -66,975.22 |
| expedite (day 44) | -6,603.75 | 0 |
| cash (day 44) | 2,304,484.75 | 1,923,449.28 |

Luna's operating result is ~53k EUR higher than the rule baseline (a heuristic,
not an optimum — see below for how). It also has ~7.6x the chargebacks (late
delivery, see the SO-0153 finding) and much lower freight spend (fewer/smaller
ocean commitments in the pipeline — this trades off resilience the run
happened not to need since demurrage was 0 for both players).

### Positive control: the model did use the public lane-diversion evidence

Day 7 tool call (`create_po`/`expedite_po` — verbatim):
```
{"type": "expedite_po", "po_id": "PO-0005"}
{"type": "expedite_po", "po_id": "PO-0006"}
```
note: *"Carrier alliance notice confirms Cape rerouting and longer Asia-Europe
transit, increasing pre-CNY execution risk. Expedited the CHG and PKG POs to
protect assembly continuity because their promised d[ay]..."* — this correctly
ties a tool call to the day-6 public news item. Recorded here as a baseline of
correct evidence use, since the acceptance bar is failure analysis, not a
blanket claim of incompetence.

### Concrete failures

**F1 — day 0, single-day work order batch exceeds visible plant capacity by 9x; drains 80-95% of on-hand components in one action.**
- Day 0 tool calls (verbatim):
  ```
  {"type": "release_work_order", "sku": "EB-STD", "qty": 25000}
  {"type": "release_work_order", "sku": "EB-PRO", "qty": 10000}
  {"type": "release_work_order", "sku": "SPK-1", "qty": 2500}
  ```
  All three returned `{"ok": true}` (`WO-0001`, `WO-0002`, `WO-0003`).
- Engine result: `kestrel/plant.py` `CAPACITY = 4000` eq-units/working-day
  (`kestrel/plant.py:11`). `release_work_order` reserves every component for
  the full order quantity immediately (`kestrel/plant.py:release_work_order`,
  lines 32-33), not per day of actual production. `screens_before.inventory.PLANT`
  at day 0: `BAT 49500, SOC 43500, DRV 81000, CASE 43500, CHG 37500, PKG 43500`.
  `screens_after.inventory.PLANT` same day: `BAT 9500, SOC 6000, DRV 8500,
  CASE 6000, CHG 2500, PKG 6000` — CHG dropped 93%, SOC/CASE/PKG ~86%, in a
  single tool-call batch.
- Downstream record: `WO-0001` (25000 EB-STD) history
  `[0 planned] [0 released] [0 running] [7 complete]` — took the plant's full
  capacity for 7 straight working days. `WO-0002` (10000 EB-PRO) did not even
  start running until day 7 (FIFO behind WO-0001), completed day 9. `WO-0003`
  (2500 SPK-1) started day 9, completed day 11. One day-0 decision thus
  committed 100% of plant capacity through day 11 and left components too low
  to react to anything else (day 4 note: *"pro and speaker work orders remain
  released pending component availability"*).
- Classification: **unclear tool** — `kestrel/agent/tools.py::ENGINE_TOOLS["release_work_order"]`
  has no `qty` bound and `build_system_brief` (`kestrel/agent/tools.py`) never
  states the 4000/day plant capacity figure, the FIFO multi-day queuing
  behavior, or that components are reserved for the *entire* order quantity
  at release rather than drawn down per day of actual production. A player
  cannot reason about pacing production against capacity when capacity is
  never disclosed. Also a **model mistake**: the model had no external reason
  to release nearly a year's worth of one day's demand in one call rather
  than a run of smaller orders, and the same 3-part batch pattern recurs
  (smaller, ~2500-unit orders) once the model is burned by the day-0
  stockout — i.e. it later self-corrected to a more conservative batch size
  without ever being told the capacity number, suggesting it inferred the
  constraint empirically rather than reading it. This is a joint failure:
  the tool did not disclose the constraint, and the model did not probe for
  one (e.g. via `get_screen("inventory")`, which does show `PLANT` line
  items but no capacity/day figure) before committing at that scale.
- This reproduces (at smaller scale, same shape) in `runs/_smoke_red_sea_1day/luna/run.json`
  day 0: `{"release_work_order","EB-STD",20000}` + `{"...EB-PRO",10000}` +
  `{"...SPK-1",5000}` = 35000 units in one call there too, confirming this is
  not a one-off sampling fluke.

**F2 — day 32/35, two failed manual `allocate_order` calls colliding with the engine's own automatic daily allocation, one with a self-contradicted quantity.**
- Day 32 tool calls (verbatim):
  ```
  {"type": "create_transfer", "src": "DC-DE", "dst": "DC-PL", "mode": "truck", "lines": {"SPK-1": 100}}
  {"type": "allocate_order", "order_id": "SO-0153", "qty": 100}
  ```
  Result of the second call: `{"ok": false, "reason": "order SO-0153 has 91
  units open, cannot allocate 100", "id": null}`. The model's own note the
  same turn: *"Reviewed C-PLCHAIN's **91-unit** open SPK-1 requirement..."* —
  it named the correct open quantity in prose one sentence before sending a
  tool call for a different number (100, matching the transfer size instead
  of the order's actual need). Classification: **model mistake** (arithmetic/
  copy inconsistency between stated reasoning and the actual call).
- Day 35 tool call (verbatim): `{"type": "allocate_order", "order_id":
  "SO-0153", "qty": 91}` → `{"ok": false, "reason": "DC-PL has 0 unallocated
  SPK-1, need 91", "id": null}`. Downstream record: `TR-0008` (the day-32
  transfer) shows `delivered` on day 34 with 100 SPK-1 into DC-PL, so stock
  did land — but `SO-0153`'s own history shows `[28 received] [35 allocated
  "fully allocated"] [36 shipped] [38 delivered]`, i.e. the engine's own
  per-day automatic allocation (driven by `set_allocation_policy`, which the
  model itself set on days 0/3/41) fully allocated the order (242 units, not
  91) on day 35 before the model's manual call executed that same day.
  `SO-0153.data.late = true` — this order shipped late and is part of the
  chargeback gap versus rule (-3,146.32 vs -414.74 at day 44).
- Classification: **unclear tool** — `allocate_order`'s description
  ("Manually allocate stock to a received order") does not say that orders
  are already allocated automatically every day per the active allocation
  policy, so a manual call is for exception cases only and can race the
  daily automatic pass with stale data from the *opening* screen. The model
  had no way to know its manual call would be evaluated against a
  same-day-updated stock/order picture rather than the morning snapshot it
  read. No cash/stock corruption resulted (`ok:false`, no side effect), so
  this cost 2 wasted tool calls, not a bad outcome by itself — but it sits
  directly next to the one late, charged-back order in this run, without a
  provable causal link (the order was late regardless of the manual
  attempts; see caveat below).

### Caveat on F2's causal link
The late/chargeback outcome on SO-0153 is **not** demonstrated to be *caused*
by the model's failed manual allocation attempts — the engine's automatic
allocation ran regardless and the shipment timing follows from
transfer/production lead times, not from the rejected calls. This is flagged
as a confusion/wasted-effort finding (unclear tool interaction), not claimed
as the reason for the late delivery. Do not read this as "the model caused
the chargeback."

### Defects for scoped fix
None identified for red_sea that require an engine code change. F1 and F2 are
tool-briefing/description gaps (`kestrel/agent/tools.py`), not engine bugs —
the engine behaved exactly as documented in its own source (capacity gating,
FIFO work-order queue, automatic daily allocation). Recommendation (for a
future scoped task, not applied here): state `CAPACITY` (eq-units/working
day) in `build_system_brief`, and note in `allocate_order`'s description that
open orders are allocated automatically each day and manual calls compete
with that pass.

---

## 2. cny_prebuild (seed 1002, start_day 0, days 60)

### Status / usage (verbatim)
- luna: `status="complete"`, `completed_days=60/60`, `usage={"prompt_tokens": 9195713, "completion_tokens": 28806, "total_tokens": 9224519, "cost": 0.7451592800000001, "is_byok": 0}`. No API errors.
- rule: `status="complete"`, `completed_days=60/60`, `usage={}`.

### Evidence table (`tasks.evidence`, cny_prebuild = `ship_slipped_pos`)

| | luna | rule |
|---|---|---|
| POs with a "China capacity" ship-slip note in history | **0** | 17: `PO-0006, PO-0008, PO-0010, PO-0013, PO-0014, PO-0015, PO-0016, PO-0017, PO-0020, PO-0021, PO-0022, PO-0023, PO-0026, PO-0027, PO-0028, PO-0029, PO-0032` |
| `create_po` calls in the whole 60-day run | **0** | 37 (continuous replenishment) |
| orders late / short (of 318 total for both) | 20 / 33 | 10 / 22 |
| revenue (day 59) | 3,723,191.00 | 4,121,220.00 |
| operating_result (day 59) | 2,521,267.13 | 2,795,932.95 |
| chargebacks (day 59) | -8,502.70 | -3,491.45 |
| cash (day 59) | 3,134,587.75 | 2,873,915.46 |

Luna never called `create_po` once in 60 days — it ran the entire task on the
component pipeline already on order at task start (`on_order` in
`screens_before.inventory.PLANT` at day 0: `BAT 74250, SOC 65250, DRV 121500,
CASE 65250, CHG 56250, PKG 65250`), which is why zero of its POs could carry
a China-capacity slip note (there were no luna-placed POs to slip). Component
on-hand stock stayed comfortably positive throughout (e.g. `BAT` never below
11,500; full trace in `runs/cny_prebuild/luna/run.json` frames 0/10/20/.../59),
so this is not a component stockout — but revenue is 9.7% lower and
operating result 9.8% lower than the rule baseline, with roughly double the
late orders and 50% more short orders. The mechanism is not proven by this
run (see caveat), but the same day-0 over-large work-order batch as red_sea
(F1, repeated below) plus zero ongoing procurement in a task explicitly built
around a Chinese New Year capacity ramp-down are circumstantially connected.

### Concrete failures

**F1 (recurrence) — day 0 batch again drains 74-93% of on-hand components in one call.**
Day 0 tool calls (verbatim): `{"release_work_order","EB-STD",20000}`,
`{"release_work_order","EB-PRO",8000}`, `{"release_work_order","SPK-1",5000}`.
`screens_before.inventory.PLANT` -> `screens_after`: `BAT 49500->11500`,
`SOC 43500->10500`, `DRV 81000->20000`, `CASE 43500->10500`, `CHG
37500->9500`, `PKG 43500->10500`. Same shape as red_sea F1, same
classification (**unclear tool**: capacity/reservation-on-release not
disclosed; **model mistake**: no attempt to pace against any capacity
figure). Confirms this is a systematic behavior of the model on this task
family, not a one-off sampling artifact.

**F3 — day 0-59, zero replenishment orders placed across a 60-day horizon that includes the Chinese New Year capacity event named in the task's own system brief.**
- The system brief (`build_system_brief`) lists `Chinese New Year` under
  "Calendar events this year" with its exact day range and ramp-down/ramp-up
  note (`kestrel/agent/tools.py`, calendar section, sourced from
  `kestrel/calendar.py::EVENTS`: `{"name": "Chinese New Year", "start_day":
  20, "end_day": 77, "note": "holiday 15-23 Feb; capacity ramps down from 25
  Jan and back up to 23 Mar"}`), and the task's own `public_brief` names CNY
  by design (task id `cny_prebuild`). The model never issued `create_po` in
  60 days (`Counter` over all 60 frames' actions: `{'allocate_order': 15,
  'create_transfer': 14, 'release_work_order': 8, 'book_container': 7,
  'set_inspection_level': 4, 'expedite_po': 3, 'set_allocation_policy': 1}`
  — `create_po` count 0).
- Downstream record/outcome: no stockout occurred (component on-hand never
  neared zero), but service degraded relative to rule: late orders 20 vs 10,
  short orders 33 vs 22, revenue -398,029 EUR (-9.7%), operating result
  -274,666 EUR (-9.8%), chargebacks -8,502.70 vs -3,491.45.
- Classification: **model mistake** (candidate) — the model had the
  information needed (calendar event in its own system brief) to plan ahead
  of a capacity crunch and simply never acted on the procurement lever at
  all in 60 days, rule-planner discipline notwithstanding. Flagged as a
  candidate rather than a confirmed root cause because this run does not
  isolate zero-procurement as the sole driver of the late/short gap — the
  day-0 over-batch (F1) and the allocation-timing issues (F4 below) run
  concurrently and are equally plausible contributors. No single tool call
  can be pointed to as "the" failure here; this is a whole-run planning gap
  evidenced by an absence of action across the entire horizon.

**F4 — six failed engine calls spanning three distinct problem classes.**
All six, verbatim (day, call, result):
1. day 34: `{"create_transfer","DC-NL","DC-DE","rail",{"EB-PRO":8000}}` ->
   `{"ok": false, "reason": "DC-NL has 0 EB-PRO, need 8000"}`. **Model
   mistake**: requested 8000 units from a node holding zero of that SKU —
   the opening/inventory screen the same day would show this (screens are
   real-time, not stale by more than one day), so this is either a stale
   read or an arithmetic slip on the source location.
2. day 44: `{"create_transfer","PLANT","DC-DE","truck",{"EB-STD":2000}}` ->
   `{"ok": false, "reason": "no such leg 'PLANT' -> 'DC-DE' via 'truck'"}`.
   **Unclear tool**: `create_transfer`'s schema (`kestrel/agent/tools.py`)
   gives `src`/`dst` as `enum: NODE_IDS` (all five network nodes, PLANT
   included) with no indication that PLANT's only outbound leg is to DC-NL
   (`kestrel/network.py::LEGS` — `('PLANT','DC-NL',...)` are the only
   PLANT-rooted keys; PLANT to any other DC is not a legal leg at all,
   finished goods must first move PLANT->DC-NL via `book_container`, then
   DC-NL->DC-DE/DC-PL via `create_transfer`). The schema's node/mode enums
   are the union across all legs, not per-pair, so a well-typed but
   topologically invalid call is only caught by the engine's runtime
   `ValueError`->`{"ok": false}`, not by the schema. This is a genuine
   tool-briefing gap: the system brief lists freight routes and inter-DC
   legs as prose bullet points (`build_system_brief`, "Freight routes and
   inter-DC legs" section) which *does* enumerate the real 4 PLANT->DC-NL
   + 8 inter-DC legs correctly — so the information exists, just not
   structurally enforced by the tool schema; the model apparently did not
   cross-reference it here.
3. day 51: `{"book_container","air",{"SPK-1":2500},"spot"}` -> `{"ok":
   false, "reason": "PLANT has 2343 SPK-1, need 2500"}`. **Model mistake**:
   requested a round number (2500, matching an earlier work-order batch
   size) rather than the actual 2343 on hand, a 157-unit (6%) overshoot.
4. day 52: `{"allocate_order","SO-0224",15}` -> `{"ok": false, "reason":
   "DC-PL has 0 unallocated EB-PRO, need 15"}` — same class as red_sea F2
   (manual allocation racing/duplicating the engine's automatic per-day
   allocation pass). **Unclear tool** (see red_sea F2).
5. day 52: `{"allocate_order","SO-0225",0}` -> `{"ok": false, "reason":
   "qty must be a positive int, got 0"}`. **Model mistake**: sent a
   zero-quantity allocation with no apparent purpose (the tool schema does
   not explicitly say `qty` must be positive, but 0 is a self-evidently
   inert request no reasoning model should emit).
6. day 54: `{"allocate_order","SO-0247",179}` -> `{"ok": false, "reason":
   "order SO-0247 cannot be allocated from state 'allocated'"}`. **Model
   mistake**: tried to allocate an order already fully allocated (the
   `orders`/`records` screen shows each order's current state; the model
   did not check it before calling).
None of the six calls had a side effect (`ok:false`, no state change) — the
cost is entirely wasted tool calls (6 of ~130 total engine calls this run),
not corrupted state.

### Defects for scoped fix
None found requiring an engine code change for cny_prebuild. F4.2 reinforces
the red_sea recommendation to disclose valid PLANT-rooted legs directly in
`create_transfer`'s tool description (today it's only in a separate prose
section of the system brief) rather than only in `kestrel/network.py::LEGS`.

---

## 3. soc_insolvency (seed 1003, start_day 60, days 45)

### Status / usage (verbatim)
- luna: `status="complete"`, `completed_days=45/45`, `usage={"prompt_tokens": 13294066, "completion_tokens": 34070, "total_tokens": 13328136, "cost": 0.8689853899999997, "is_byok": 0}`. No API errors. Cost/day (~$0.0193/day average) is roughly double red_sea's and higher than cny_prebuild's — see the day-60 records-screen defect below for the dominant driver.
- rule: `status="complete"`, `completed_days=45/45`, `usage={}`.

### Evidence table (`tasks.evidence`, soc_insolvency = `cancelled_soc_pos`, `scorecard`)
(`scorecard` is read live from `world.scorecards`, which is not part of the
persisted `run.json`/`records` state; recomputed here by deterministically
replaying each run's own recorded actions from `prepare_task("soc_insolvency")`
through `kestrel.agent.tasks.make_event_driver` — the same replay
`_prepare_or_resume` uses for `--resume` — so these numbers are reproduced,
not measured live in the original process. This is the one exception in this
document to "read only from run.json"; it is called out because
`kestrel.agent.tasks.evidence()` itself is unreachable from a finished run's
JSON without such a replay, which is itself worth the scoped-fix owner's
attention — see Defects below.)

| | luna | rule |
|---|---|---|
| S-SOC POs cancelled for insolvency | 11: `PO-0023, PO-0028, PO-0029, PO-0030, PO-0031, PO-0032, PO-0034, PO-0039, PO-0040, PO-0042, PO-0043` | 23: `PO-0047, PO-0053, PO-0058, PO-0059, PO-0060, PO-0065, PO-0071, PO-0073, PO-0079, PO-0084, PO-0085, PO-0087, PO-0092, PO-0093, PO-0094, PO-0098, PO-0099, PO-0100, PO-0102, PO-0104, PO-0108, PO-0109, PO-0110` |
| S-SOC scorecard (replayed) | `{"otif_30d": 1.0, "ppm_30d": 6465.28, "updated_day": 86}` | `{"otif_30d": 1.0, "ppm_30d": 8000.0, "updated_day": 86}` |
| operating_result (final) | 4,184,384.00 | 4,680,317.25 |
| revenue (final) | 6,652,396.40 | 7,080,015.40 |
| late / short orders | 43 / 74 | 25 / 31 |
| chargebacks (final) | -26,011.52 | -10,719.49 |
| expedite spend (final) | -28,238.45 | -978.75 |
| writeoffs (final) | -270,944.87 | -116,084.85 |
| cash (final) | 4,968,678.49 | 4,875,042.00 |

### Positive control: correct, fast reaction to the insolvency event
The override sets S-SOC to `insolvent` on day 65 (`kestrel.conditions.Conditions._set_health`).
The public news item first appears day 66 (`{"day": 66, "source": "S-SOC",
"title": "S-SOC enters insolvency", "body": "Open orders will not ship;
administrators appointed.", "kind": "supplier"}`, first visible in
`screens_before.news` on day 67's opening message). The model issued 11
`cancel_po` calls for every still-cancellable S-SOC PO the very next day
(day 67) — a one-day reaction lag from public evidence to correct, complete
action across every affected open PO, none missed. Recorded as a baseline of
competent behavior.

### Concrete failures

**F5 — repeated `expedite_po` calls on POs already expedited, ignoring a visible field.**
Four wasted calls, verbatim: day 61 `{"expedite_po","PO-0012"}` -> `{"ok":
false, "reason": "PO PO-0012 is already expedited"}`; day 61
`{"expedite_po","PO-0023"}` -> same reason; day 62 `{"expedite_po","PO-0008"}`
and `{"expedite_po","PO-0009"}` -> same reason (twice); day 66
`{"expedite_po","PO-0009"}` -> same reason again (third attempt on the same
PO, five days after the first). `d['records']['PO-0009']['data']['expedited']
== True` (and likewise for PO-0008/0012/0023) — this is a plain field on the
PO record, visible in full via `get_screen("records")` or the PO's own
history the model had already fetched. Classification: **model mistake** —
the information needed to avoid the call was already public and had already
been read by the model earlier in the run (PO-0009 appears in the day-62 and
day-66 records screens the model fetched); this is not a hidden-state
problem.

**F6 — attempted to place a component order with an unqualified supplier the system brief explicitly flags as unqualified.**
Day 62 (verbatim): `{"type": "create_po", "supplier": "S-BRK", "component":
"SOC", "qty": 2000, "requested_day": 75, "incoterm": "FOB"}` -> `{"ok":
false, "reason": "S-BRK is not a qualified supplier; run qualify_supplier
first (45 days)"}`. `build_system_brief`'s supplier section states this for
every supplier including S-BRK: `"...qualified at start=False."`
(`kestrel/network.py::SUPPLIERS["S-BRK"].qualified == False`, confirmed by
direct import). Classification: **model mistake** — the model was
diversifying away from the insolvent S-SOC (a sound instinct, and it did
separately call `qualify_supplier`/`request_audit` on day 60 for a different
supplier), but picked an alternate supplier its own briefing had already
marked unqualified, rather than one already qualified for the SOC component.

**F7 — quantity-vs-availability mismatches in `allocate_order`, worse than red_sea/cny_prebuild's.**
Day 62 (verbatim): `{"type": "allocate_order", "order_id": "SO-0291", "qty":
266}` -> `{"ok": false, "reason": "DC-DE has 3 unallocated SPK-1, need
266"}` — an 88x overshoot, the largest quantity mismatch observed in any of
the three tasks analyzed so far. Day 65: `{"type": "allocate_order",
"order_id": "SO-0327", "qty": 0}` -> `{"ok": false, "reason": "qty must be a
positive int, got 0"}`, same zero-quantity pattern as cny_prebuild F4.5.
Classification: **model mistake** for both (available stock and non-zero
quantity are read directly off the inventory/orders screens the model
itself called earlier the same turn in most of these cases — see
transcript day 62 and day 65 request bodies in `runs/curated/soc_insolvency/luna/transcript.jsonl`).

### Defects for scoped fix

**D1 — `get_screen("records")` returns an unfiltered 83,950-character (~40,000+ prompt-token, by the API's own count) payload on the very first call of a 60-day-warm-up task, and this recurs on ~every subsequent day it is called (39 of 45 days in this run).**
- Reproduction: day 60 (the task's first day; `soc_insolvency` has
  `start_day=60`), the model's second HTTP call of the day issued 5
  `get_screen` calls in one turn: `suppliers`, `inventory`, `forecast`,
  `records`, `customers`. Their tool-result payload sizes (chars): `suppliers
  1,380`, `inventory 1,909`, `forecast 338`, **`records 83,950`**, `customers
  7,306`. The single `records` result is 88% of that turn's tool-result
  bytes and pushed the call's own `usage.prompt_tokens` to 40,141 (from
  4,615 on the immediately preceding call in the same day) — i.e. this one
  tool result alone cost roughly 35,000+ prompt tokens.
- Root cause (read from `kestrel/screens.py:114`, not modified): `records =
  {kind: [record_view(r) for r in world.records.open(kind)] for kind in
  CLOSED}` — every currently-*open* record of every kind, each serialized in
  full (`record_view`, full state-transition history included), with no
  kind filter, date filter, or pagination. Breakdown of the day-60 payload
  by kind (count open, chars): `po 34 (25,133)`, `ret 86 (22,486)`,
  `invoice_out 98 (17,902)`, `order 19 (6,733)`, `asn 18 (3,504)`, `receipt
  17 (3,497)`, `booking 8 (3,357)`, `work_order 2 (490)`, `chargeback 2
  (361)` (`lot`, `invoice_in`, `contract`, `transfer`, `credit_note`,
  `qualification`, `audit` all 0 open at day 60). `po` and `ret` together
  are >56% of the payload.
- Effect on cost: this run made 39 distinct `get_screen("records")` calls
  over 45 days (counted from fresh `tool_calls` in each transcript
  response, not from the repeated message-history copies each subsequent
  HTTP call carries). At ~35-85k+ characters per call plus the
  `KEEP_VERBATIM_DAYS=2` window re-sending each day's blocks verbatim for
  two more days before `_maybe_trim` collapses them, this single tool is
  the most plausible dominant driver of soc_insolvency's $0.869/45-day cost
  versus red_sea's $0.488/45-day and cny_prebuild's $0.745/60-day — the
  three tasks are otherwise structurally similar, but only soc_insolvency
  starts at `start_day=60`, so its first `records` call already carries 60
  days of accumulated open records instead of a handful.
- Classification: **unclear tool / observation too large** (a simulator-
  adjacent defect in `kestrel/agent/tools.py::call_tool`'s `get_screen`
  dispatch and/or `kestrel/screens.py::build`'s `records` construction, not
  in the planner/procurement/logistics engine modules proper). Not fixed
  here per the controller's scope (record for a scoped fix only). A minimal
  fix would let `get_screen("records")` take an optional `kind` filter, or
  cap/paginate each kind's list, or drop full history arrays from the
  summary view and require a per-ID lookup for detail.

**D2 — `tasks.evidence()`'s `scorecard` field is not reconstructable from a finished run's own `run.json`.**
`evidence(world, task_id)` for `soc_insolvency` reads `world.scorecards.get("S-SOC")`
(`kestrel/agent/tasks.py:236`), but `world.scorecards` is never written into
`_base_result`'s persisted `records` dict (`kestrel/agent/runner.py:227`
only serializes `world.records`). The only way this document could report
the scorecard evidence field above was to re-run `prepare_task` and replay
every recorded action through `make_event_driver`/`world.end_day()` from
scratch — which works today only because the engine is fully deterministic
given the same seed and action sequence (`tests/test_tasks.py` already
covers this determinism claim), but means the task's own advertised
`evidence()` contract is not actually queryable from the deliverable
`run.json` artifact without re-executing the simulation. Classification:
**simulator/tooling defect** (evidence-capture gap between `runner.py` and
`tasks.py::evidence`). Minimal fix: persist `world.scorecards` (a small
dict, not hidden state) into `_base_result`, or have `run.json` store the
full `evidence()` dict directly at completion.

---

## 4. black_friday (seed 1004, start day of 2026-10-20 = absolute day 288, days 45)

### Status / usage (verbatim)
- luna: `status="complete"`, `completed_days=45/45`, `usage={"prompt_tokens": 18508008, "completion_tokens": 27034, "total_tokens": 18535042, "cost": 1.4314844199999999, "is_byok": 0}`. No API errors. This is the highest-cost run of the five (still under the 3 USD/run guard) — `start_day=288` means the model's first-day `get_screen("records")` call already carries 288 days of accumulated open records (see D1/D3 recurrence below, worse here than soc_insolvency's `start_day=60`).
- rule: `status="complete"`, `completed_days=45/45`, `usage={}`.

### Evidence table (`tasks.evidence`, black_friday = `black_friday_week_qty`, `baseline_week_qty`)

| | luna | rule |
|---|---|---|
| Black Friday week (23-29 Nov) order qty | 22,581 | 22,581 |
| baseline week (9-15 Nov) order qty | 5,302 | 5,302 |
| ratio | 4.26x | 4.26x |
| revenue (final) | 23,245,097.20 | 23,237,501.20 |
| operating_result (final) | 14,828,171.62 | 14,838,528.74 |
| late / short orders (of 1,722 total, both) | 27 / 25 | 27 / 25 |
| chargebacks (final) | -18,410.24 | -18,410.24 |

Order *quantity* evidence is identical between players because customer
order arrival is exogenous (demand-generator driven, not planner-driven) —
this evidence field measures the scenario, not the player, and is expected
to match. What differs is fulfillment, and here luna and rule are close:
operating result within 0.07%, late/short counts identical. With 288 days
of prior (rule-generated) history already baked into the shared checkpoint
and ample on-hand stock at handoff (`PLANT.BAT` 115,316 on hand, `EB-STD`
16,923 finished on hand with 25.5 days of cover at day 288), this is the one
task where luna's last-45-days decisions had the least relative leverage
over the outcome, and it performed on par with the rule baseline rather than
below it (contrast red_sea -0k/+53k favorable, cny_prebuild -274k,
soc_insolvency -496k unfavorable).

### No failed engine calls this run
Every one of this run's engine tool calls returned `{"ok": true}` (13 calls
across days 288-331; verified against `runs/black_friday/luna/run.json`).
None of the F2/F4/F5/F7-style quantity-mismatch or stale-state failures seen
in the other three tasks appear here. The shared circumstance across those
failures elsewhere was a materially constrained inventory/allocation
position; black_friday's shared 288-day checkpoint left the plant and DCs
comparatively well-stocked at handoff, which is consistent with (but does
not prove) those failures being provoked by tight-inventory decision
pressure rather than being a constant, state-independent error rate.

### F1 (recurrence, muted) — day 288 batch again, but proportionate this time
Day 288 (verbatim): `{"release_work_order","EB-STD",30000}`,
`{"release_work_order","EB-PRO",8000}`, `{"release_work_order","SPK-1",10000}`,
plus `{"book_container","sea_air",{"EB-STD":10000,"EB-PRO":2000,"SPK-1":2500},"spot"}`.
`PLANT` on-hand before -> after: `BAT 115,316->57,316`, `SOC 85,852->37,852`,
`CASE 98,608->50,608`, `CHG 91,900->53,900`, `PKG 98,608->50,608` — roughly a
50% draw this time, not the 80-95% seen in red_sea/cny_prebuild, because the
day-288 checkpoint carried much larger component stock. Also notable: the
model chose `sea_air` (a faster, costlier hybrid mode) for the Black Friday
lead-time push and set `C-PLCHAIN`/`C-BIGBOX` ahead of `C-MARKET`/`C-WEB` in
allocation priority — a reasonable proactive read of the approaching demand
event from the calendar section of its own system brief. Not classified as
a failure; recorded because it shows the same one-shot large-batch release
pattern recurs even when its consequences are less severe, reinforcing that
this is model habit (see red_sea F1), not an artifact of one bad prompt.

### Defects for scoped fix

**D3 — the `records` screen's "open" records for `asn` and `receipt` are unbounded and now dominate the oversized payload (extends D1).**
- At day 288, `get_screen("records")` returned 128,330 characters (up from
  83,950 at soc_insolvency's day 60 — this grows with elapsed simulated
  time, consistent with the mechanism below), pushing that call's
  `usage.prompt_tokens` to 58,244 (from 5,859 the call before). Per-kind
  breakdown of that payload: `asn 193 open (37,821 chars)`, `receipt 192
  open (39,741 chars)`, `ret 86 open (22,725 chars)`, `invoice_out 94 open
  (17,441 chars)`, `order 15 open (5,438 chars)`, `po 6 open (3,624 chars)`
  — `asn`+`receipt` alone are 60% of the payload, versus `po`'s 25,133/83,950
  (30%) at soc_insolvency's day 60. `closed_counts` for the same call shows
  `asn: 0` and `receipt: 0` closed out of hundreds ever created.
- Root cause (`kestrel/records.py`, read only, not modified): `LEGAL["asn"]
  = set()`, `LEGAL["receipt"] = set()`, `CLOSED["asn"] = set()`,
  `CLOSED["receipt"] = set()` — these two record types have no transitions
  and no closed states defined at all; they are single-state event
  documents (an ASN or goods-receipt notice, created once, never
  transitioned). `Records.open(kind)` (`kestrel/records.py:55`) is `[r for
  r in self.all(type) if r.state not in CLOSED[type]]` — for a type with an
  empty `CLOSED` set, this is *every record of that type ever created*, for
  the life of the run. `kestrel/screens.py:114`'s `records` builder then
  serializes `world.records.open(kind)` for every kind unconditionally,
  including these two, so the `records` screen's "open" bucket for `asn`/
  `receipt` grows monotonically for the full simulated year with no cap,
  independent of whether anything about them still needs planner attention.
- Classification: **simulator/tooling defect**, distinct from D1 (D1 is "no
  filter/pagination knob exists"; D3 is "two specific record types were
  never given a closed-state concept, so the existing `open()`/`CLOSED`
  convention silently degenerates to `all()` for them"). Not fixed here.
  Minimal scoped fix: either give `asn`/`receipt` a closed-state marker
  (e.g. closed once the matching `receipt`/`lot` exists) so `Records.open`
  behaves as intended, or have `screens.py`'s `records` builder cap/exclude
  the by-construction-single-state types from the "open" bucket (e.g. show
  only the last N days' worth) instead of relying on `CLOSED`.

Not a defect, but worth flagging alongside D1/D3 for the scoped-fix owner:
these two defects compound directly — a longer `start_day` (many of a real
year's simulated days already elapsed before the model's first turn) makes
every `get_screen("records")` call larger, which is exactly the ordering
observed across the three tasks with nonzero `start_day`/elapsed history
(red_sea/cny_prebuild `start_day=0`: no such spike; soc_insolvency
`start_day=60`: 83,950 chars; black_friday `start_day=288`: 128,330 chars).

---

## 5. invoice_mismatch (seed 1005, start_day 0, days 45)

### Status / usage (verbatim)
- luna: `status="complete"`, `completed_days=45/45`, `usage={"prompt_tokens": 5875556, "completion_tokens": 17626, "total_tokens": 5893182, "cost": 0.4469099499999999, "is_byok": 0}`. No API errors. Zero failed engine tool calls this run (every call in `run.json`'s frames has `result.ok == true`).
- rule: `status="complete"`, `completed_days=45/45`, `usage={}`.

### Evidence table (`tasks.evidence`, invoice_mismatch = `mismatched_invoices`, `rolled_bookings`)

| | luna | rule |
|---|---|---|
| mismatched invoices | `["INV-0003"]` | `["INV-0003"]` |
| rolled bookings | **`[]`** | `["BK-0004", "BK-0009", "BK-0010", "BK-0012", "BK-0013"]` |
| operating_result (final) | 1,839,655.48 | 1,788,966.14 |
| revenue (final) | 2,717,138.00 | 2,699,056.00 |
| late / short orders | 0 / 14 | 1 / 15 |
| chargebacks (final) | 0 | -199.92 |

### Headline finding — the task's own scheduled event silently failed to fire for the model player

This is the most significant finding in this document, because it is a
**task-construction defect only detectable by actually running a real
player**, not by the rule baseline (which the tests in `tests/test_tasks.py`
already exercise and which was used to validate the task) — exactly the
class of thing Task 19 exists to catch.

- `TASKS["invoice_mismatch"]["overrides"] = [(21, _force_invoice_mismatch),
  (21, _force_rolled_booking)]` (`kestrel/agent/tasks.py:121`). Both fire on
  day 21 via `make_event_driver`, called just before `world.end_day()`.
- `_force_rolled_booking` (`kestrel/agent/tasks.py:76-88`, read only, not
  modified):
  ```
  booked = sorted((b for b in world.records.open("booking") if b.state == "booked"), key=lambda b: b.id)
  if not booked:
      return
  ```
  It is a silent no-op if no booking is in state `booked` on day 21 in that
  player's own (by-then-diverged) world.
- luna's first `book_container` call of the entire run was on **day 30**
  (verbatim: `{"type": "book_container", "mode": "sea_air", "lines":
  {"EB-STD": 8000, "EB-PRO": 8000, "SPK-1": 2500}, "rate_type": "spot"}`).
  Its full action list for days 0-29 (verbatim from `run.json`) is
  `set_inspection_level`x4, `set_allocation_policy`, `release_work_order`x3
  (day 0), `release_work_order`x3 (day 15), `create_transfer`x2 (day 17),
  `dispute_invoice` (day 22) — no freight booking at all before day 30. So
  at day 21, luna had **zero** bookings in any state, `booked` included, and
  `_force_rolled_booking` returned immediately with no effect.
- Downstream record/outcome: `evidence(world, "invoice_mismatch")["rolled_bookings"]`
  is `[]` for the luna run versus `["BK-0004", "BK-0009", "BK-0010",
  "BK-0012", "BK-0013"]` for the rule run (the first of which, `BK-0004`, is
  the forced one; the other four rolled later through the normal `ROLL_PROB`
  draw, unrelated to the override). The task was designed so every player
  would see one forced, reproducible "booking rolled" event by day 21
  (`docs/tasks.md`: *"force-rolls exactly one booked booking -- the earliest
  by id -- through cut_off then rolled"*) — but that guarantee only holds
  if the player already has an open booking by then, which the task
  definition does not require or check.
- Classification: **simulator/task defect**, not a model mistake — the
  model did nothing wrong per se (delaying the first freight booking to day
  30 is a legitimate planning choice given ample day-0 finished-goods
  cover), but the task's premise that this event is "reproducible" and will
  visibly occur for whichever player runs it is false whenever a player's
  own decisions leave no eligible booking at the override day. The mismatched-
  invoice override (`_force_invoice_mismatch`) does not have this problem:
  it depends only on a PO reaching `inspected`, which happens from the
  automatic procurement lifecycle regardless of planner choices, so it fired
  identically for both players here. The rolled-booking override is the
  only one of the five tasks' scheduled events shown in this document to be
  conditionally skippable by ordinary, defensible planner behavior.

### Positive control: correct, fast dispute of the forced invoice mismatch
Day 22 (one day after `INV-0003` was created day 21, verbatim):
`{"type": "dispute_invoice", "invoice_id": "INV-0003"}` -> `{"ok": true}`.
`INV-0003` history: `[21 blocked "created"] [22 disputed "disputed by
planner"] [32 accepted "dispute resolved at -6%"] [32 paid "paid"]` — matches
the tool's documented behavior exactly ("resolves 10 days later at -6%").
Recorded as a second baseline of competent, evidence-driven behavior
(alongside red_sea's expedite reaction and soc_insolvency's cancellation
reaction) — this document is a failure analysis, not a blanket claim of
incompetence, and three of five tasks show at least one clean instance of
the model correctly identifying and acting on a forced/organic exception
within one day of its first public appearance.

### No engine-rejected tool calls this run
Unlike the other four tasks, every engine call in this run succeeded
(`result.ok == true` throughout `runs/invoice_mismatch/luna/run.json`). No
F2/F4/F5/F7-style quantity or state mismatches to report here — consistent
with the black_friday observation that these errors cluster around tighter
inventory/allocation pressure, which this run's smaller day-0 batch (compare
to red_sea/cny_prebuild) and generally conservative pacing avoided.

### Defects for scoped fix
**D4 — `_force_rolled_booking`'s "reproducible" guarantee is player-dependent, not task-dependent.** See the headline finding above for the full
reproduction. Minimal scoped fix options (not applied here): (a) have
`make_event_driver` retry the override on subsequent days until a `booked`
booking exists (bounded, e.g. through day 21 + N), so it still fires
regardless of when the player first books freight; or (b) if no eligible
booking exists by day 21, force a bare minimal one into existence for the
sole purpose of the override (mirroring how `_force_invoice_mismatch`
manufactures its own record); or (c) explicitly document in `docs/tasks.md`
that `rolled_bookings` can legitimately be empty for a player who has not
booked freight by the override day, and adjust `evidence()`/any downstream
grading to treat an empty list as "event not applicable to this player,"
not "event missed." Whichever fix is chosen, it should not change
`_force_invoice_mismatch`'s behavior, which does not have this problem.

---

## 5b. invoice_mismatch, revision 2 (after D4 fix)

Re-run of `invoice_mismatch` (seed 1005, start_day 0, days 45) against the
fixed code (D1-D4 and the `SOURCE_HASH` module-list fix all applied; see
`.superpowers/sdd/2026-09-15-kestrel-world/task-19-fix-report.md`). Same
model (`openai/gpt-5.6-luna`), same seed, same rule baseline procedure as
section 5. Runs live at `runs/invoice_mismatch/<player>/` and
`runs/curated/invoice_mismatch/<player>/`; section 5's original runs are
preserved at `runs/invoice_mismatch_rev1/` and
`runs/curated/invoice_mismatch_rev1/` and are not touched by this section.

### Status / usage (verbatim from `run.json`)
- luna: `status="complete"`, `completed_days=45/45`, `usage={"prompt_tokens": 2216708, "completion_tokens": 22812, "total_tokens": 2239520, "cost": 0.18186752999999997, "is_byok": 0}`. Well under the 3 USD/run cap.
- rule: `status="complete"`, `completed_days=45/45`, `usage={}`.
- `source_hash="c7d35171a020"` for both (identical between luna and rule, confirming the same fixed source state for the whole run, consistent with the `SOURCE_HASH` fix's exclusion of `api.py`/`artifact.py` from unrelated concurrent edits).

### Evidence table (`tasks.evidence`, now persisted in `run.json["evidence"]` per D2 -- read directly from the file, no replay needed)

| | luna | rule |
|---|---|---|
| `mismatched_invoices` | `[]` | `["INV-0003"]` |
| `rolled_bookings` | `["BK-0002"]` | `["BK-0004", "BK-0009", "BK-0010", "BK-0012", "BK-0013"]` |
| `rolled_booking_day` (D4 field) | **37** | **21** |
| revenue (final) | 2,666,625.00 | 2,699,056.00 |
| operating_result (final) | 1,839,031.71 | 1,788,966.14 |
| delivered orders (of 240 total, both) | 206 | 207 |
| late / short delivered orders | 8 / 19 | 1 / 15 |
| chargebacks (final, count) | -4,390.68 (8) | -199.92 (1) |

### The rolled-booking event: fired for both players, on different days (D4 fix confirmed working)

For **rule**, `rolled_booking_day=21` — same as revision 1: the rule planner
already had a `booked` booking on the override's originally-scheduled day, so
the retry loop's first check (day 21) fires immediately, matching the
pre-fix single-shot behavior exactly for a player who was never affected by
the bug.

For **luna**, `rolled_booking_day=37` — the fix's intended effect. Luna's
first (and, through day 37, only) freight booking of the entire run is on
day 37 (verbatim, `runs/invoice_mismatch/luna/run.json` frame day 37):
`{"type": "book_container", "mode": "air", "lines": {"EB-PRO": 2000}, "rate_type": "spot"}` -> `{"ok": true, "reason": "", "id": "BK-0002"}`, with the
day's own note: *"CNY and tight freight are creating near-term pro
shortages; booked BK-0002 air freight for 2,000 EB-PRO from PLANT to DC-NL
as a protective replenishment."* `make_event_driver`'s retry loop (bounded to
the task's day-21-through-44 window) checked days 21-36 and found no eligible
`booked` booking each time (a no-op, exactly as in revision 1's finding), then
on day 37 -- the same day BK-0002 was created, since the override runs after
that day's actions but before `world.end_day()` -- found it and fired:
`BK-0002` was cut off, rolled, and its `cutoff_day` pushed out by 7 days, all
within day 37. The model noticed and correctly assessed the forced event the
very next day (day 38, verbatim): *"Reviewed the rolled air booking BK-0002,
inventory, orders, transfers, work orders, and inbound invoices. BK-0002
remains legally active in rolled status with cutoff day 45; no cancellation
or duplicate booking was warranted."* -- BK-0002's cutoff day 45 is exactly
37 + 1 (air's normal one-day cutoff) + 7 (the override's roll penalty), so
the model's own read of the record matches the engine's actual math. Under
the pre-fix code this run would have shown `rolled_bookings=[]` for luna
exactly as revision 1 did (a different model action sequence, but the same
underlying "no booking yet on day 21" condition), silently failing to
reproduce the scheduled event; instead it now fires 16 days late but
correctly, and the run's own evidence records exactly when.

### A second, unscoped instance of the same underlying problem (observed, not fixed)

Revision 1's finding for D4 explicitly stated the invoice-mismatch override
(`_force_invoice_mismatch`) "does not have this problem" because reaching PO
state `inspected` doesn't depend on planner choices. This revision-2 run
shows that claim is narrower than it looked: `_force_invoice_mismatch`
*also* found no eligible PO in state `inspected` at its day-21 check for
luna this time, and silently no-opped -- `mismatched_invoices` is `[]` for
luna's run, and no invoice with the forced 10%-overprice signature
(`amount == expected * 1.10` at creation) exists anywhere in luna's
`run.json["records"]`. What happened instead: PO-0003 organically drew the
8% mismatch probability in `procurement._invoice` on day 20 (one day *before*
the override check), creating `INV-0003` at `1.06x` its expected amount
through pure chance, independent of the override; luna disputed it correctly
the next day (day 21, verbatim: *"Validated blocked invoice INV-0003 against
PO-0003: billed EUR 103,032 versus expected EUR 97,200, a EUR 5,832
mismatch. Disputed the invoice rather than paying it."* -> `{"type": "dispute_invoice", "invoice_id": "INV-0003"} -> {"ok": true}`), and it resolved
10 days later at -6% exactly per the documented rule. `evidence()`'s
`mismatched_invoices` filter (`amount > expected * 1.01`) misses this
resolved invoice entirely, because dispute resolution's -6% pushes
`1.06 * 0.94 = 0.9964` below the 1.01 threshold once settled -- a second,
separate quirk of the evidence formula (it only catches an *unresolved*
mismatch), also not in this pass's scope. **This is reported here for the
record, not fixed**: the controller's D4 ruling scoped the retry fix to the
rolled-booking override specifically ("it should not change
`_force_invoice_mismatch`'s behavior"), so `_force_invoice_mismatch` was left
exactly as revision 1 found it, timing-fragile precondition and all. The
practical outcome this run (an organic mismatch substituting for the forced
one, both correctly handled by the model) means the *scenario* -- "a
mismatched invoice appears and must be handled" -- still occurred and was
still handled correctly, even though the specific forced mechanism that was
supposed to guarantee it did not fire.

### Cost, tool-call pattern, and remaining engine-rejected calls

Luna's cost fell from revision 1's $0.4469/45 days to $0.1819/45 days on the
fixed code -- consistent with (but not proof of, since the action sequences
differ) D1/D3's records-screen-size fixes reducing `get_screen("records")`
payload size, since `asn`/`receipt` no longer accumulate without bound. 9 of
luna's engine calls this run returned `{"ok": false}` (days 29, 34, 35, 41,
43 -- inventory-quantity mismatches and one zero-quantity `allocate_order`,
e.g. day 34: `{"type": "allocate_order", "order_id": "SO-0151", "qty": 513}`
-> `{"ok": false, "reason": "DC-PL has 0 unallocated EB-STD, need 513"}`),
the same F2/F4/F5/F7-style pattern documented in sections 1-3 of this
document; not re-classified in depth here since D1-D4 (not model behavior)
were this pass's subject.

---

## 5c. invoice_mismatch, revision 3

Re-run of `invoice_mismatch` after the controller's round-2 ruling fixed the
two concerns section 5b raised at its own end: (1) `_force_invoice_mismatch`
now uses the identical `(day, until_day, fn)` retry mechanism as
`_force_rolled_booking` (retries day 21 through day 44 until a PO is
`inspected`, records `mismatch_forced_day`); (2)
`evidence()["mismatched_invoices"]` is now derived from each invoice's
state/history (ever `"blocked"`/`"disputed"`) instead of its current,
dispute-resolution-mutable `amount` field. Same model, seed, and rule
baseline procedure as sections 5/5b. Revision 2's runs are preserved intact
at `runs/invoice_mismatch_rev2/` and `runs/curated/invoice_mismatch_rev2/`
and are not touched by this section; section 5b's own text above is
unedited.

### Status / usage (verbatim from `run.json`)
- luna: `status="complete"`, `completed_days=45/45`, `usage={"prompt_tokens": 1759912, "completion_tokens": 15399, "total_tokens": 1775311, "cost": 0.13243009000000003, "is_byok": 0}`. Well under the 3 USD/run cap.
- rule: `status="complete"`, `completed_days=45/45`, `usage={}`.
- `source_hash="c7d35171a020"` for both -- unchanged from revision 2's value, since round 2's fix only touched `kestrel/agent/tasks.py` (already inside the module list `SOURCE_HASH` hashes) and not `api.py`/`artifact.py`.

### Evidence table (`tasks.evidence`, from `run.json["evidence"]`)

| | luna | rule |
|---|---|---|
| `mismatched_invoices` | `["INV-0003", "INV-0004"]` | `["INV-0003"]` |
| `mismatch_forced_day` (round-2 field) | **22** | **21** |
| `rolled_bookings` | `[]` | `["BK-0004", "BK-0009", "BK-0010", "BK-0012", "BK-0013"]` |
| `rolled_booking_day` | **None** | **21** |
| revenue (final) | 2,470,088.00 | 2,699,056.00 |
| operating_result (final) | 1,701,625.49 | 1,788,966.14 |
| delivered orders (of 240 total, both) | 210 | 207 |
| late / short delivered orders | 27 / 44 | 1 / 15 |
| chargebacks (final, count) | -18,375.06 (27) | -199.92 (1) |

### Both forced events, and how the model handled each

**`mismatch_forced_day=22` for luna (vs. 21 for rule) -- the round-2 retry
fix confirmed working, and it also confirms round 2's own diagnosis of the
bug.** PO-0004 reached state `inspected` on day 21 (verbatim, from
`run.json["records"]`'s PO history), the override's originally-scheduled
day -- yet it did not fire that day: the override check runs before that
day's own `procurement.advance()`/`_invoice()` step, which is what promotes
a PO into `inspected` in the first place, so a PO reaching `inspected`
*during* day 21 is invisible to day 21's own check. The retry loop tried
again on day 22, found PO-0004 now sitting in `inspected` from the day
before, and fired: `INV-0004` was created `blocked` that day at the forced
10% overprice -- `89,718.75` vs expected `81,562.50` (exactly `expected *
1.10`) as created. Luna could not see `INV-0004` yet on day 22 (it was
created by the override, which runs *after* that day's tool calls, not
before), so its day 22 note reads: *"INV-0003 remains correctly disputed
pending resolution; no new invoice or booking action is available."* It
appeared on day 23's opening screen and luna disputed it the same day
(verbatim, and matching the invoice's amount at that point in time exactly):
*"Reviewed the new blocked INV-0004 against PO-0004. It is €89,718.75 versus
the expected €81,562.50, so I disputed it to avoid paying the mismatch."*
-> `{"type": "dispute_invoice", "invoice_id": "INV-0004"} -> {"ok": true}`.
Ten days later the dispute resolved at -6% per the documented rule
(`89,718.75 * 0.94 = 84,335.625`), which is the amount `run.json`'s final
record shows -- the two figures are the same invoice at two different
points in its life, not a discrepancy. There is also a *second*, genuinely
organic mismatch this run: `INV-0003` (created day 20, `96,850.08` vs
expected `97,200.00` in its final state, the `1.06 * 0.94`
post-dispute-resolution signature from `procurement._invoice`'s own 8%
draw), which luna disputed correctly on day 21, before the forced one ever
appeared. Both `INV-0003` and `INV-0004` are correctly captured in
`mismatched_invoices` under the round-2 fix; under the pre-round-2 formula,
`INV-0003` (resolved to `0.9964x` expected by the time the run ends) would
have been silently dropped, exactly as section
5b found.

**`rolled_booking_day=None` for luna this run -- the round-2 diagnosis's
predicted "never eligible" case, observed for real.** Luna made zero
`book_container` calls across all 45 days of this run (verified against
`run.json["frames"]`; the model's own day 22 note even says so explicitly:
*"The blank sailing affects future cut-offs, but no active booking exists to
roll."*). The retry loop checked every day from 21 through 44, found no
`booked` booking on any of them, and correctly left `rolled_booking_day` as
`None` and `rolled_bookings` as `[]` rather than fabricating an event or
crashing -- this is the legitimate "event not applicable to this player"
outcome the original D4 finding anticipated but revision 2's run (where
luna booked, just late) hadn't actually exercised. Rule's booking timing is
unchanged (`rolled_booking_day=21`, same five `rolled_bookings` as every
prior revision).

### Everything else this run

Financially, luna trails rule more than in revision 2 (operating result
1,701,625.49 vs 1,788,966.14, about -4.9% vs revision 2's -2.7% and revision
1's -19.4%; not a trend claim -- three different code states, three
different action sequences, no statistics run on this). Late/short delivery
counts are noticeably worse than revision 2 (27/44 vs 8/19), consistent with
never booking any freight to DC-NL at all this run -- with no booked
container to protect service against, the plant->DC-NL leg simply never
uses freight this run, which is a real planning gap for the model, not
scored or investigated further here (out of this pass's scope, which is the
defect fixes and re-run, not model-behavior evaluation). 5 of luna's engine
calls returned `{"ok": false}` this run (days 27 x3 `allocate_order`
zero-unallocated-stock, day 42 a zero-quantity `create_transfer` line, day
44 a zero-quantity `allocate_order`) -- the same F2/F4/F5/F7-style pattern
as every other run in this document.
