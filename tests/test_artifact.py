import json
import re
from pathlib import Path

from kestrel import artifact

FIXTURE_RUN = Path(__file__).resolve().parents[1] / "runs" / "_smoke_red_sea_1day" / "luna" / "run.json"

# Words that must never appear in the embedded data payload (they name engine-internal
# fields kestrel/screens.py's HIDDEN set already keeps out of screens(), so a hit here
# would mean the artifact bypassed that boundary somewhere).
HIDDEN_WORDS = ["lane_age", "rate_regime", "supplier_health", "alloc_age", "port_q",
                "strike_until", "defects_true", "rng", "override"]

MAX_BYTES = 12 * 1024 * 1024  # generous ceiling for a single-run smoke build; full builds target 8MB


def _fake_year_run(tmp_path) -> Path:
    """A tiny stand-in year run so the test doesn't pay the ~11s cost of a real
    361-day rule-planner run; ensure_year_run() only computes one if the cache
    file is missing, so writing it here short-circuits that."""
    stub = {
        "schema_version": 1, "run_id": "full-year-rule-1-stub", "task_id": "full_year",
        "task_version": 1, "source_hash": "stub", "player": "rule", "model": None,
        "parameters": {}, "started_at": None, "initial_day": 0,
        "requested_days": 1, "completed_days": 1, "status": "complete", "usage": {},
        "frames": json.loads(FIXTURE_RUN.read_text())["frames"],
        "records": json.loads(FIXTURE_RUN.read_text())["records"],
    }
    path = tmp_path / "year_run.json"
    path.write_text(json.dumps(stub))
    return path


def _extract_runs_payload(html: str) -> str:
    """Just the window.KESTREL_RUNS JSON -- the actual simulation data. Deliberately
    excludes window.KESTREL_FINDINGS_HTML: that is free-text prose from
    docs/model-findings.md, which the brief explicitly allows to discuss hidden-state
    vocabulary in prose (task-21-brief.md: "only allowed hits are inside the findings
    prose if it discusses them"), so it must not be scanned for HIDDEN_WORDS -- see
    review-21-verdict.md finding I-2."""
    m = re.search(r"window\.KESTREL_RUNS = (.*?);\n", html, re.S)
    assert m, "expected the KESTREL_RUNS data script in the artifact"
    return m.group(1)


def _extract_full_data_script(html: str) -> str:
    """Both embedded globals, for checks that legitimately apply to all embedded
    JSON regardless of content (e.g. </script>-escaping)."""
    m = re.search(r"window\.KESTREL_RUNS = (.*?);\nwindow\.KESTREL_FINDINGS_HTML = (.*?);\n", html, re.S)
    assert m, "expected the KESTREL_RUNS/KESTREL_FINDINGS_HTML data script in the artifact"
    return m.group(1) + m.group(2)


def test_build_produces_self_contained_html(tmp_path):
    out = tmp_path / "kestrel-demo.html"
    artifact.build(out_path=out, runs=[FIXTURE_RUN], year_run=_fake_year_run(tmp_path))

    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    size = out.stat().st_size
    assert size < MAX_BYTES, f"artifact is {size} bytes, over the {MAX_BYTES} limit"

    # no network dependency of any kind. The one legitimate "http://" is the SVG
    # XML namespace URI (createElementNS) reused verbatim from frontend/app.js --
    # it is a namespace identifier, never fetched, and appears nowhere near an
    # actual resource-loading attribute or call.
    assert "https://" not in html
    non_svg_ns = [line for line in html.splitlines() if "http://" in line and "createElementNS" not in line]
    assert not non_svg_ns, f"unexpected http:// reference(s): {non_svg_ns}"
    for tag_attr in re.findall(r'\b(?:src|href)\s*=\s*"([^"]*)"', html):
        assert not tag_attr or tag_attr.startswith("#"), f"external reference found: {tag_attr!r}"

    # </script> must never appear un-escaped inside the embedded JSON (it would
    # otherwise prematurely close the data <script> tag) -- applies to both globals
    full_payload = _extract_full_data_script(html)
    assert "</" not in full_payload or "<\\/" in full_payload
    assert not re.search(r"(?<!\\)</", full_payload), "unescaped </ inside embedded JSON payload"

    # hidden simulator-internal words must not leak into the actual simulation data
    # (window.KESTREL_RUNS only -- window.KESTREL_FINDINGS_HTML is free-text prose
    # that is allowed to discuss them, see _extract_runs_payload's docstring)
    runs_payload = _extract_runs_payload(html)
    for word in HIDDEN_WORDS:
        assert word not in runs_payload, f"hidden-state word {word!r} leaked into embedded run data"


def test_build_includes_real_run_status(tmp_path):
    out = tmp_path / "kestrel-demo.html"
    artifact.build(out_path=out, runs=[FIXTURE_RUN], year_run=_fake_year_run(tmp_path))
    html = out.read_text(encoding="utf-8")
    m = re.search(r"window\.KESTREL_RUNS = (.*?);\n", html, re.S)
    runs = json.loads(m.group(1))
    smoke = next(r for r in runs if r["task_id"] == "_smoke_red_sea_1day")
    # the fixture run is a genuinely incomplete 1-day smoke run; the artifact must
    # report that truthfully, never fabricate a complete one
    assert smoke["status"] == "incomplete"
    assert smoke["player"] == "luna"
    assert len(smoke["frames"]) == 1
    # provenance must survive publication: which engine revision produced the run
    assert smoke["source_hash"] == json.loads(FIXTURE_RUN.read_text())["source_hash"]


def _reconstruct_open_ids(compacted_frames: list) -> list:
    """Mirrors kestrel.artifact._HYDRATE_JS's reconstruction in Python, for tests:
    replays each frame's full-form or delta-form `records` against a running
    {type: {id: state}} snapshot and returns, per frame, {type: set(ids)}."""
    current: dict = {}
    out = []
    for frame in compacted_frames:
        sa = frame.get("screens_after")
        if sa is None:
            out.append(None)
            continue
        if frame["full"]:
            current = {kind: dict(pairs) for kind, pairs in sa["records"].items()}
        else:
            for kind, entry in sa["records"].items():
                current.setdefault(kind, {})
                for rid, state in entry.get("a", []):
                    current[kind][rid] = state
                for rid in entry.get("r", []):
                    current[kind].pop(rid, None)
        out.append({kind: set(ids) for kind, ids in current.items()})
    return out


def test_compact_frame_keeps_action_outcomes_and_record_ids():
    """Every id referenced from a compacted frame (after reconstructing the
    full/delta records encoding, exactly as the hydration script does) must
    resolve in the *compacted* (pruned) records archive, not just the original
    run.json's -- round 2 prunes the archive, so checking against the unpruned
    dict would pass even if pruning dropped something a frame still needed."""
    run = json.loads(FIXTURE_RUN.read_text())
    compacted = artifact.compact_run(run)
    for original, frame in zip(run["frames"], compacted["frames"]):
        assert frame["actions"] == original["actions"]
        assert frame["status"] == original["status"]
        assert frame["error"] == original["error"]
    for snapshot in _reconstruct_open_ids(compacted["frames"]):
        if snapshot is None:
            continue
        for kind, ids in snapshot.items():
            for rid in ids:
                assert rid in compacted["records"]


BLACK_FRIDAY_RUN = Path(__file__).resolve().parents[1] / "runs" / "black_friday" / "rule" / "run.json"


def test_archive_drops_pre_start_closed_unreferenced_records():
    """Round 2, controller ruling: black_friday's rule-planner warm-up runs from
    day 0 to its ~day-288 start, closing thousands of records the task's own 45
    captured frames never touch again. A record closed before the run's first
    frame and never referenced anywhere in a frame should not survive pruning."""
    run = json.loads(BLACK_FRIDAY_RUN.read_text())
    first_day = min(f["day"] for f in run["frames"])
    assert first_day > 0, "this test needs a task that starts its captured frames well after day 0"

    compacted = artifact.compact_run(run)
    dropped = set(run["records"]) - set(compacted["records"])
    assert dropped, "expected pruning to drop at least one pre-start, unreferenced, closed record"

    sample = next(iter(dropped))
    rv = run["records"][sample]
    assert max(h_day for h_day, _, _ in rv["history"]) < first_day, (
        f"dropped record {sample} should have stopped changing before the run started")
    # and it must genuinely be unreferenced anywhere in the kept frames
    referenced = artifact._keep_record_ids(run)
    assert sample not in referenced


REAL_RUN = Path(__file__).resolve().parents[1] / "runs" / "red_sea" / "rule" / "run.json"


def test_thin_frame_keeps_every_open_record_not_just_same_day_changes():
    """Regression for review-21-verdict.md finding I-1: a thin (non-checkpoint) frame
    must show every record that was actually open that day, not only the ones that
    happened to transition state on that exact day. Reviewer's own check: day 11 of
    runs/red_sea/rule/run.json (a thin day, 11 % 7 != 0, no new exception that day)
    has 15 open POs in the real run.json; reconstructing the compacted artifact's
    round-2 full/delta records encoding for day 11 must show the same 15, not the 1
    a same-day delta would have kept (the original, fix-round-1 bug)."""
    run = json.loads(REAL_RUN.read_text())
    day11_index = next(i for i, f in enumerate(run["frames"]) if f["day"] == 11)
    original_day11 = run["frames"][day11_index]
    assert not artifact._is_checkpoint(original_day11, day11_index, len(run["frames"]),
                                        artifact.TASK_CHECKPOINT_EVERY), (
        "day 11 must be a thin (non-checkpoint) frame for this regression test to mean anything")
    real_open_pos = len(original_day11["screens_after"]["records"]["po"])
    assert real_open_pos == 15, f"expected the reviewer's known-good count of 15, got {real_open_pos}"
    original_ids = {r["id"] for r in original_day11["screens_after"]["records"]["po"]}

    compacted = artifact.compact_run(run)
    assert compacted["frames"][day11_index]["full"] is False
    reconstructed = _reconstruct_open_ids(compacted["frames"])
    assert reconstructed[day11_index]["po"] == original_ids


def test_screens_before_deduped_against_previous_screens_after():
    """Round 2, controller ruling: an incomplete/error frame's screens_before is
    normally byte-identical to the previous frame's screens_after (nothing runs
    between world.end_day() and the next world.screens() call), so storing it
    again is pure duplication. No real run currently has a mid-run incomplete
    frame to exercise this on, so this constructs one from the fixture run."""
    base = json.loads(FIXTURE_RUN.read_text())
    day0 = base["frames"][0]
    same_screens = day0["screens_after"]
    different_screens = {**same_screens, "finance": {**same_screens["finance"], "cash": -1}}

    synthetic = dict(base)
    synthetic["frames"] = [
        day0,
        {**day0, "day": 1, "date": "2026-01-06", "screens_after": None,
         "screens_before": same_screens, "status": "incomplete", "error": "boom"},
        {**day0, "day": 2, "date": "2026-01-07", "screens_after": None,
         "screens_before": different_screens, "status": "incomplete", "error": "boom again"},
    ]
    compacted = artifact.compact_run(synthetic)

    # day 1's screens_before equals day 0's screens_after -> omitted (None), to be
    # restored by the hydration script, not the Python side.
    assert compacted["frames"][1]["screens_after"] is None
    assert compacted["frames"][1]["screens_before"] is None

    # day 2's screens_before genuinely differs from the (still day-0) previous
    # screens_after -> kept as-is.
    assert compacted["frames"][2]["screens_before"] == different_screens

    # the very first frame always keeps its own screens_before if it were ever an
    # incomplete frame itself (nothing to dedupe against)
    first_only = dict(base)
    first_only["frames"] = [{**day0, "screens_after": None, "screens_before": same_screens,
                              "status": "incomplete", "error": "boom"}]
    compacted_first = artifact.compact_run(first_only)
    assert compacted_first["frames"][0]["screens_before"] == same_screens


def test_discover_runs_only_lists_existing_files(tmp_path):
    runs_dir = tmp_path / "runs"
    (runs_dir / "red_sea" / "rule").mkdir(parents=True)
    (runs_dir / "red_sea" / "rule" / "run.json").write_text("{}")
    found = artifact.discover_runs(runs_dir)
    assert found == [runs_dir / "red_sea" / "rule" / "run.json"]
