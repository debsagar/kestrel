"""Standalone offline HTML artifact builder (Task 21, SPEC/brief in
.superpowers/sdd/2026-09-15-kestrel-world/task-21-brief.md).

Bundles `frontend/{index.html,style.css,app.js}` verbatim (never modified --
this module only reads them), plus compacted replay data for every available
recorded run and one full rule-planner year, into a single dependency-free
HTML file: no server, no network fetch, no CDN, no Python needed to view it.

Frame compaction scheme is documented in `docs/artifact-schema.md`; read that
alongside this module before changing either.

Ponytail: one module, no templating library, plain string formatting for the
handful of HTML slots this needs.
"""
import json
import re
from pathlib import Path

from .agent.tasks import SOURCE_HASH, TASKS, rule_day
from .screens import record_view
from .world import World

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
RUNS_DIR = ROOT / "runs"
DEFAULT_OUT = ROOT / "artifacts" / "kestrel-demo.html"
DEFAULT_YEAR_RUN = RUNS_DIR / "full_year" / "rule" / "run.json"
FINDINGS_PATH = ROOT / "docs" / "findings-summary.html"  # short hand-written summary; full evidence in model-findings.md

YEAR_SEED = 1
YEAR_DAYS = 361
# Round 2 (controller ruling): the full year (361 days) checkpoints every 14 days
# to keep its size down; the five named tasks (45-60 days) stay at every 7 days --
# they're short enough that the more-frequent checkpoint doesn't cost much and it
# keeps more full-fidelity days for a run a manager is more likely to scrub closely.
YEAR_CHECKPOINT_EVERY = 14
TASK_CHECKPOINT_EVERY = 7
PLAYERS = ("rule", "luna")
# A Kestrel record id: kestrel/records.py::PREFIX is 2-4 uppercase letters, then
# "-", then a zero-padded number (RecordStore.new: f"{PREFIX[type]}-{n:04d}"). Used
# to find record-id references inside actions/results/report/exceptions/news text
# without hand-listing every field name that might carry one.
_RECORD_ID_RE = re.compile(r"^[A-Z]{2,4}-\d+$")
# screens_after keys frontend/app.js never reads (grep confirms: no screens.suppliers,
# screens.market, or screens.forecast reference anywhere in app.js). Dropping them from
# every frame is duplicate/unused metadata, not a material outcome -- see brief item 3.
_UNUSED_SCREEN_KEYS = ("suppliers", "market", "forecast")

# The public frame/records/usage/metadata contract -- mirrors kestrel/api.py's
# own RUN_FIELDS allow-list, so an embedded run is exactly what the live API
# would have served for the same run.json.
from .agent.tasks import PUBLIC_RUN_FIELDS as RUN_FIELDS


# -- full rule-planner year (no task overrides, plain World) ----------------

def _build_year_run() -> dict:
    world = World(YEAR_SEED)
    frames = []
    for _ in range(YEAR_DAYS):
        if world.done:
            break
        frames.append(rule_day(world))
    return {
        "schema_version": 1, "run_id": f"full-year-rule-{YEAR_SEED}", "task_id": "full_year",
        "task_version": 1, "source_hash": SOURCE_HASH, "player": "rule", "model": None,
        "parameters": {}, "started_at": None, "initial_day": 0,
        "requested_days": YEAR_DAYS, "completed_days": len(frames),
        "status": "complete" if len(frames) == YEAR_DAYS else "incomplete",
        "usage": {}, "frames": frames,
        "records": {rid: record_view(world.records.get(rid)) for rid in world.records.ids()},
    }


def ensure_year_run(path: Path) -> dict:
    """Load a cached full-year run from `path`, generating and caching it if missing."""
    path = Path(path)
    if path.is_file():
        return json.loads(path.read_text())
    data = _build_year_run()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


# -- run discovery (read-only under runs/) -----------------------------------

def discover_runs(runs_dir: Path = RUNS_DIR) -> list[Path]:
    """Every `runs/<task_id>/<player>/run.json` that exists right now, for the five
    named tasks. Never writes under runs/; safe to call while another process is
    still populating it -- whatever exists at call time is what gets embedded.

    `runs/curated/<task_id>/<player>/run.json` is preferred over
    `runs/<task_id>/<player>/run.json` when both exist: per docs/model-findings.md,
    `runs/curated/` holds the public-safe copy the findings doc's own evidence
    table cites (identical run.json content today, byte for byte, wherever both
    exist -- the "curated" distinction is about the sibling transcript.jsonl,
    which this module never reads). Falls back to the plain path so tasks
    without a curated copy yet are still included."""
    runs_dir = Path(runs_dir)
    paths = []
    for task_id in TASKS:
        for player in PLAYERS:
            curated = runs_dir / "curated" / task_id / player / "run.json"
            plain = runs_dir / task_id / player / "run.json"
            if curated.is_file():
                paths.append(curated)
            elif plain.is_file():
                paths.append(plain)
    return sorted(paths)


# -- frame compaction ---------------------------------------------------------
# See docs/artifact-schema.md for the full rationale and schema. Summary:
#  - screens_before is dropped whenever screens_after exists (the only case
#    the frontend ever reads screens_before is when screens_after is None,
#    i.e. an incomplete/error day); when it's present but equals the previous
#    frame's screens_after (round 2), it's dropped too and restored by the
#    hydration script instead of being stored twice.
#  - every 7th day for a named task (14th for the full year -- round 2), any
#    day with a new exception, and the run's last frame keep screens_after in
#    full (a "checkpoint" frame); other days are "thin".
#  - the embedded `records` archive is pruned to what frames/findings can
#    actually reference (round 2) -- see "records-archive scope" below.
#  - in EVERY frame, checkpoint or thin, `records` is the complete list of
#    records the real screens.records[type] showed as open that day -- not a
#    same-day-only delta (fix round 1, review-21-verdict.md finding I-1: a
#    delta silently dropped every open-but-unchanged record's id from the
#    view on ~85% of days). A record is still referenced by id, not embedded
#    (see "Id-reference hydration" below), and every frame still shows every
#    record actually open that day once hydrated -- but round 2 replaced the
#    naive "repeat the full {id, state} list on every frame" encoding with a
#    running-snapshot delta (add/remove/change since the previous frame),
#    reconstructed by the hydration script, because the full-list-every-frame
#    encoding turned out to cost about the same whether a frame was a
#    checkpoint or not (records dominate a frame's size either way), which
#    defeated the point of having thin frames at all. See "Records delta
#    encoding" below. `customers[*].open_orders` isn't stored per frame at
#    all any more; it's derived at hydration time by filtering the
#    reconstructed `records.order` list by `data.customer`.
#  - thin frames additionally keep only calendar/finance/customers/inventory
#    (all small, bounded per-day structures) plus exceptions_new/news_new --
#    only the entries appended since the previous frame, not the whole
#    cumulative list (world.exceptions/world.news only ever grow by appending,
#    so this is an exact delta, not an approximation); the hydration script
#    concatenates it onto a running accumulator, so the "to date" count and
#    both panels are exactly as accurate as storing the full list every frame
#    would be, at a fraction of the size. Checkpoint frames keep the whole
#    screen, including the full cumulative exceptions/news list, as a resync
#    point.
#  - actions/results and the day's report (log/new_exceptions/news) are kept
#    in full on every frame, checkpoint or not -- action outcomes are never
#    thinned.


def _records_snapshot(records_field: dict) -> dict:
    """{type: {id: state}} for one day's real (pre-compaction) screens.records."""
    return {kind: {r["id"]: r["state"] for r in items}
            for kind, items in records_field.items() if kind != "closed_counts"}


def _records_full_form(snapshot: dict) -> dict:
    """{type: [[id, state], ...]} -- the wire form for a checkpoint frame: a
    complete, self-contained resync point, two-element arrays instead of
    {"id":..,"state":..} objects to save the repeated key names at this scale."""
    return {kind: [[rid, state] for rid, state in ids.items()] for kind, ids in snapshot.items()}


def _records_delta_form(prev_snapshot: dict, snapshot: dict) -> dict:
    """{type: {"a": [[id, state], ...], "r": [id, ...]}} for a thin frame: only
    what changed since the previous frame's snapshot (added, state-changed, or
    removed -- i.e. closed/no-longer-open). The hydration script applies this to
    its own running copy of the previous frame's reconstructed snapshot, so the
    full per-day open-records listing is still recovered exactly -- this changes
    the wire encoding, not the materiality guarantee (fix round 1) that every
    frame shows every record open that day."""
    delta = {}
    for kind in set(prev_snapshot) | set(snapshot):
        before, after = prev_snapshot.get(kind, {}), snapshot.get(kind, {})
        added_or_changed = [[rid, state] for rid, state in after.items() if before.get(rid) != state]
        removed = [rid for rid in before if rid not in after]
        entry = {}
        if added_or_changed:
            entry["a"] = added_or_changed
        if removed:
            entry["r"] = removed
        if entry:
            delta[kind] = entry
    return delta


def _drop_open_orders(customers: dict) -> dict:
    out = {}
    for cid, c in customers.items():
        c2 = dict(c)
        del c2["open_orders"]
        out[cid] = c2
    return out


def _is_checkpoint(frame: dict, index: int, total: int, checkpoint_every: int) -> bool:
    if frame["day"] % checkpoint_every == 0:
        return True
    if (frame.get("report") or {}).get("new_exceptions"):
        return True
    return index == total - 1


def compact_frame(frame: dict, checkpoint: bool, prev_screens_after: dict | None,
                   prev_records_snapshot: dict, prev_exc_len: int, prev_news_len: int,
                   is_first: bool) -> tuple[dict, dict, int, int]:
    """Returns (compacted_frame, this_frame's_records_snapshot, exceptions_len,
    news_len). The snapshot is {} and the lengths are unchanged (pass through
    prev_exc_len/prev_news_len) when this frame had no screens_after (incomplete/
    error day) -- callers should carry the previous non-empty values forward
    across such a gap, which `compact_run` does."""
    out = {"day": frame["day"], "date": frame["date"], "actions": frame["actions"],
           "note": frame["note"], "report": frame["report"], "status": frame["status"],
           "error": frame["error"], "full": checkpoint}
    sa = frame["screens_after"]
    if sa is None:
        # incomplete/error day: screens_after doesn't exist, so screens_before
        # (real, point-in-time data) is the only screen the frontend can show.
        out["screens_after"] = None
        # Round 2: screens_before at the start of day D is, in practice, exactly
        # the previous frame's screens_after at the end of day D-1 -- nothing runs
        # between world.end_day() and the next world.screens() call. When they're
        # equal, omit screens_before entirely and let the hydration script copy it
        # forward from the previous frame instead of storing a full duplicate
        # screen. The first frame has no previous frame to dedupe against, so it
        # always keeps its own (per the controller ruling).
        if is_first or frame["screens_before"] != prev_screens_after:
            out["screens_before"] = frame["screens_before"]
        else:
            out["screens_before"] = None
        return out, {}, prev_exc_len, prev_news_len
    snapshot = _records_snapshot(sa["records"])
    slim = {k: v for k, v in sa.items() if k not in _UNUSED_SCREEN_KEYS}
    slim["customers"] = _drop_open_orders(sa["customers"])
    if checkpoint:
        slim["records"] = _records_full_form(snapshot)
        out["screens_after"] = slim
        return out, snapshot, len(sa["exceptions"]), len(sa["news"])
    out["screens_after"] = {
        "calendar": slim["calendar"], "finance": slim["finance"], "customers": slim["customers"],
        "inventory": slim["inventory"],
        # Round 2: only the entries appended since the previous frame, not a
        # padded tail of the whole cumulative list -- world.exceptions/world.news
        # only ever grow by appending, so this is an exact (not approximate)
        # encoding; the hydration script concatenates it onto a running
        # accumulator to recover the true cumulative list at every frame,
        # cheaply, at every day, instead of storing the same list over and over.
        "exceptions_new": sa["exceptions"][prev_exc_len:],
        "news_new": sa["news"][prev_news_len:],
        "records": _records_delta_form(prev_records_snapshot, snapshot),
    }
    return out, snapshot, len(sa["exceptions"]), len(sa["news"])


# -- records-archive scope (round 2, controller ruling) ----------------------
# A task's warm-up (kestrel.agent.tasks.prepare_task runs the rule planner from
# day 0 to the task's start_day before either player acts) creates thousands of
# records that close out long before the task's own captured frames even begin
# -- e.g. black_friday starts around day 288 with over 8000 records already on
# the books, most from months of pre-task operation. Keeping the full archive
# means paying for all of that history even though no frame or finding can ever
# show it. A record earns a place in the embedded archive only if it is:
#  (a) open on at least one frame of the run (its id appears in that frame's own
#      screens_after.records or a customer's open_orders -- exactly what the
#      real desk would have shown that day), or
#  (b) referenced anywhere in a frame's actions/results/report/exceptions/news
#      (a generic record-id-shaped string scan, not a hand-picked field list --
#      covers e.g. an exception's "ref" or an action's "po_id" without needing
#      to know every field name that might carry one), or
#  (c) changed state during the run's own day range (a history entry whose day
#      falls between the run's first and last captured frame, inclusive).
# A record closed before the run started and never mentioned again fails all
# three and is dropped.

def _scan_record_ids(value, found: set) -> None:
    if isinstance(value, str):
        if _RECORD_ID_RE.match(value):
            found.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            _scan_record_ids(v, found)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _scan_record_ids(v, found)


def _keep_record_ids(run: dict) -> set:
    frames = run["frames"]
    keep = set()
    for f in frames:
        sa = f.get("screens_after")
        if sa is not None:
            for kind, items in sa["records"].items():
                if kind == "closed_counts":
                    continue
                keep.update(r["id"] for r in items)
            for c in sa["customers"].values():
                keep.update(o["id"] for o in c["open_orders"])
            _scan_record_ids(sa.get("exceptions"), keep)
            _scan_record_ids(sa.get("news"), keep)
        _scan_record_ids(f.get("actions"), keep)
        _scan_record_ids(f.get("report"), keep)
    days = [f["day"] for f in frames]
    if days:
        lo, hi = min(days), max(days)
        for rid, rv in run["records"].items():
            if any(lo <= h_day <= hi for h_day, _, _ in rv["history"]):
                keep.add(rid)
    return keep


def _prune_records(run: dict) -> dict:
    keep = _keep_record_ids(run)
    return {rid: rv for rid, rv in run["records"].items() if rid in keep}


def compact_run(run: dict, checkpoint_every: int = TASK_CHECKPOINT_EVERY) -> dict:
    frames = run["frames"]
    total = len(frames)
    compacted = []
    prev_screens_after = None
    prev_records_snapshot = {}
    prev_exc_len = prev_news_len = 0
    for i, f in enumerate(frames):
        checkpoint = _is_checkpoint(f, i, total, checkpoint_every)
        cf, snapshot, prev_exc_len, prev_news_len = compact_frame(
            f, checkpoint, prev_screens_after, prev_records_snapshot, prev_exc_len, prev_news_len, is_first=(i == 0))
        compacted.append(cf)
        prev_screens_after = f.get("screens_after")
        if snapshot:  # an incomplete/error frame's empty {} must not erase the last real snapshot
            prev_records_snapshot = snapshot
    out = dict(run)
    out["frames"] = compacted
    out["records"] = _prune_records(run)
    return out


def _findings_html(path: Path = FINDINGS_PATH) -> str | None:
    return path.read_text() if path.is_file() else None


# -- hydration script: expands {id, state} references back to full record views --
# This is new code written for the artifact, not a modification of frontend/app.js;
# it runs before app.js's module script and only rewrites the plain data object
# app.js reads, using the same record shape screens.py already produces
# (record_view: id/type/state/created_day/history/data). `state` is taken from the
# per-frame pair, not the archive, because the archive only holds each record's
# *final* state -- overwriting it is what makes a mid-run frame show that record's
# real point-in-time status (e.g. "in_production" on day 11 even though the same
# PO is "paid" by the archive's/day 45's reckoning).
_HYDRATE_JS = """
(function () {
  function hydratePairs(byId, pairs) {
    // pairs: [[id, state], ...] -> full record objects with that day's state
    return pairs.map(function (p) {
      var rec = byId[p[0]];
      if (!rec) return rec;
      var copy = Object.assign({}, rec);
      copy.state = p[1];
      return copy;
    });
  }
  function applyDelta(current, delta) {
    // current: {type: {id: state}}, mutated in place to match this frame's day
    for (var kind in delta) {
      if (!current[kind]) current[kind] = {};
      (delta[kind].a || []).forEach(function (p) { current[kind][p[0]] = p[1]; });
      (delta[kind].r || []).forEach(function (id) { delete current[kind][id]; });
    }
  }
  function fromFullForm(recordsFull) {
    var current = {};
    for (var kind in recordsFull) {
      var map = {};
      recordsFull[kind].forEach(function (p) { map[p[0]] = p[1]; });
      current[kind] = map;
    }
    return current;
  }
  function snapshotToPairs(current) {
    var out = {};
    for (var kind in current) {
      out[kind] = Object.keys(current[kind]).map(function (id) { return [id, current[kind][id]]; });
    }
    return out;
  }
  (window.KESTREL_RUNS || []).forEach(function (run) {
    var byId = run.records || {};
    var lastScreensAfter = null;
    var current = {}; // running {type: {id: state}} snapshot, round 2 records-delta reconstruction
    var exceptions = []; // running cumulative lists, round 2 exceptions/news-delta reconstruction
    var news = [];
    (run.frames || []).forEach(function (frame) {
      var sa = frame.screens_after;
      if (sa) {
        // full (checkpoint) frames resync from a complete snapshot; thin frames
        // apply a delta against the running state -- either way, sa.records/
        // sa.exceptions/sa.news end up the same shape a live day would have had.
        if (frame.full) {
          current = fromFullForm(sa.records);
          exceptions = sa.exceptions.slice();
          news = sa.news.slice();
        } else {
          applyDelta(current, sa.records);
          exceptions = exceptions.concat(sa.exceptions_new || []);
          news = news.concat(sa.news_new || []);
          delete sa.exceptions_new;
          delete sa.news_new;
        }
        sa.exceptions = exceptions.slice();
        sa.news = news.slice();
        sa.records = {};
        var pairsByType = snapshotToPairs(current);
        for (var kind in pairsByType) sa.records[kind] = hydratePairs(byId, pairsByType[kind]);
        var orders = sa.records.order || [];
        for (var cid in sa.customers) {
          sa.customers[cid].open_orders = orders.filter(function (o) { return o && o.data && o.data.customer === cid; });
        }
        lastScreensAfter = sa;
      } else if (frame.screens_before === null && lastScreensAfter) {
        // Round 2: an omitted screens_before (kestrel/artifact.py's compact_frame
        // dropped it because it equaled the previous frame's screens_after) is
        // restored here instead of being stored twice.
        frame.screens_before = lastScreensAfter;
      }
    });
  });
})();
"""


# -- assembly ------------------------------------------------------------------

def _load_embed_run(path: Path) -> dict:
    """Load one runs/<task_id>/<player>/run.json for embedding, keyed by its
    directory names (matches kestrel/api.py's GET /api/runs convention, which
    is what lets a differently-named copy of a run -- e.g. a CLI smoke test --
    still be addressed consistently)."""
    data = json.loads(path.read_text())
    data = dict(data)
    data["task_id"] = path.parent.parent.name
    data["player"] = path.parent.name
    filtered = {k: data[k] for k in RUN_FIELDS if k in data}
    return compact_run(filtered)


def build(out_path: Path = DEFAULT_OUT, runs: list[Path] | None = None,
          year_run: Path = DEFAULT_YEAR_RUN) -> None:
    out_path = Path(out_path)
    if runs is None:
        runs = discover_runs()

    year_data = {k: v for k, v in ensure_year_run(year_run).items() if k in RUN_FIELDS}
    embedded = [compact_run(year_data, checkpoint_every=YEAR_CHECKPOINT_EVERY)]
    for p in runs:
        embedded.append(_load_embed_run(Path(p)))

    css = (FRONTEND / "style.css").read_text()
    js = (FRONTEND / "app.js").read_text()
    index_html = (FRONTEND / "index.html").read_text()

    runs_json = json.dumps(embedded).replace("</", "<\\/")
    findings_json = json.dumps(_findings_html()).replace("</", "<\\/")

    data_script = (f"<script>\nwindow.KESTREL_RUNS = {runs_json};\n"
                   f"window.KESTREL_FINDINGS_HTML = {findings_json};\n</script>\n"
                   f"<script>{_HYDRATE_JS}</script>")
    app_script = f'<script type="module">\n{js}\n</script>'

    page = index_html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")
    if '<script type="module" src="app.js"></script>' not in page:
        raise RuntimeError("frontend/index.html no longer has the expected app.js script tag; "
                            "artifact.py's assembly needs updating to match")
    page = page.replace('<script type="module" src="app.js"></script>', data_script + "\n" + app_script)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    build()
    print(f"wrote {DEFAULT_OUT} ({DEFAULT_OUT.stat().st_size / 1e6:.2f} MB)")
