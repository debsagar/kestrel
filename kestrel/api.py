"""Small in-memory HTTP boundary for live Kestrel worlds."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from . import calendar as cal, planner
from .agent import runner, tools
from .screens import record_view
from .world import World


MAX_WORLDS = 32
MAX_AUTOPILOT_DAYS = cal.N_DAYS
RUNS_DIR = runner.RUNS_DIR
LIVE_RUNS_DIR = RUNS_DIR / "live"
# Fields of a run.json that are the public frame/records/usage/metadata contract; run.json
# already holds no secrets (transcripts live in a separate transcript.jsonl the CLI writes),
# but this allow-list keeps the API from ever forwarding a future field it hasn't reviewed.
from .agent.tasks import PUBLIC_RUN_FIELDS as RUN_FIELDS
# Test hook: monkeypatched to an httpx.MockTransport in tests/test_api.py, exactly as
# tests/test_agent.py injects a transport into kestrel.agent.runner.run(transport=...).
_LLM_TRANSPORT = None


@dataclass
class Session:
    world: World
    frames: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    screens_before: dict | None = None
    # Guards every day-mutating route (actions/end_day/autopilot/llm_day) for this session --
    # not just llm_day. Non-reentrant and non-blocking: a second mutating call on the same
    # session while one is in flight is refused with 409 rather than queued, since llm_day can
    # hold it for the length of a multi-round-trip network loop.
    mutation_lock: Lock = field(default_factory=Lock)
    llm_system_msg: dict | None = None
    llm_day_blocks: list = field(default_factory=list)
    llm_day_meta: list = field(default_factory=list)
    llm_usage: dict = field(default_factory=dict)


app = FastAPI(title="Kestrel")
_sessions: dict[str, Session] = {}
_lock = RLock()  # ponytail: one lock is enough for 32 local demo sessions.


def _session(world_id: str) -> Session:
    try:
        return _sessions[world_id]
    except KeyError:
        raise HTTPException(404, "world not found") from None


def _acquire_session(world_id: str) -> Session:
    """Look up a session and claim its mutation_lock, or raise. Every route that mutates
    a session's world (actions/end_day/autopilot/llm_day) must go through this so they
    exclude each other, not just concurrent calls to the same route."""
    with _lock:
        session = _session(world_id)
    if not session.mutation_lock.acquire(blocking=False):
        raise HTTPException(409, "another request is already mutating this session's day")
    return session


def _records(world: World) -> dict:
    return {record_id: record_view(world.records.get(record_id)) for record_id in world.records.ids()}


def _reject(reason: str) -> dict:
    return {"ok": False, "reason": reason, "id": None}


def _invalid_action(action: dict) -> str | None:
    for key in ("qty", "requested_day", "containers_per_month", "percent"):
        if key in action and type(action[key]) is not int:
            return f"{key} must be an integer"
    lines = action.get("lines")
    if isinstance(lines, dict) and any(type(qty) is not int for qty in lines.values()):
        return "line quantities must be integers"
    return None


def _apply(session: Session, actions: Any) -> list[dict]:
    if not isinstance(actions, list):
        return [_reject("request body must be a list of actions")]
    if session.world.done:
        return [_reject("episode finished") for _ in actions] or [_reject("episode finished")]
    if session.screens_before is None:
        session.screens_before = session.world.screens()
    results = []
    for action in actions:
        invalid = _invalid_action(action) if isinstance(action, dict) else "action must be an object"
        result = _reject(invalid) if invalid else session.world.apply(action)
        session.pending.append({"action": action, "result": result})
        results.append(result)
    return results


def _end_day(session: Session, note: str = "") -> dict:
    if session.world.done:
        raise HTTPException(409, "episode finished")
    before = session.screens_before or session.world.screens()
    report = session.world.end_day()
    session.frames.append({
        "day": report["day"], "date": report["date"], "screens_before": before,
        "actions": session.pending, "note": note, "report": report,
        "screens_after": session.world.screens(), "status": "complete", "error": None,
    })
    session.pending, session.screens_before = [], None
    return report


def _frames(session: Session) -> list[dict]:
    frames = list(session.frames)
    if session.pending:
        screen = session.world.screens()
        frames.append({
            "day": session.world.day, "date": screen["calendar"]["date"],
            "screens_before": session.screens_before, "actions": session.pending,
            "note": "", "report": None, "screens_after": screen,
            "status": "incomplete", "error": None,
        })
    return frames


@app.post("/api/worlds")
def create_world(payload: Any = Body(...)):
    seed = payload.get("seed") if isinstance(payload, dict) else None
    if type(seed) is not int:
        raise HTTPException(400, "seed must be an integer")
    with _lock:
        if len(_sessions) >= MAX_WORLDS:
            raise HTTPException(503, "world limit reached")
        world_id = uuid4().hex
        _sessions[world_id] = Session(World(seed))
        return {"id": world_id}


@app.get("/api/worlds/{world_id}/screens")
def screens(world_id: str):
    with _lock:
        return _session(world_id).world.screens()


@app.post("/api/worlds/{world_id}/actions")
def actions(world_id: str, payload: Any = Body(...)):
    session = _acquire_session(world_id)
    try:
        with _lock:
            return _apply(session, payload)
    finally:
        session.mutation_lock.release()


@app.post("/api/worlds/{world_id}/end_day")
def end_day(world_id: str, payload: Any = Body(None)):
    note = payload.get("note", "") if isinstance(payload, dict) else ""
    if not isinstance(note, str):
        raise HTTPException(400, "note must be a string")
    session = _acquire_session(world_id)
    try:
        with _lock:
            return _end_day(session, note)
    finally:
        session.mutation_lock.release()


@app.post("/api/worlds/{world_id}/autopilot")
def autopilot(world_id: str, request: Request):
    raw = request.query_params.get("days")
    if raw is None or not raw.isascii() or not raw.isdecimal():
        raise HTTPException(400, "days must be a positive integer")
    days = int(raw)
    if not 1 <= days <= MAX_AUTOPILOT_DAYS:
        raise HTTPException(400, f"days must be between 1 and {MAX_AUTOPILOT_DAYS}")
    session = _acquire_session(world_id)
    try:
        with _lock:
            if session.world.done:
                raise HTTPException(409, "episode finished")
            reports = []
            for _ in range(min(days, cal.N_DAYS - session.world.day)):
                batch = planner.plan_day(session.world)
                _apply(session, batch)
                reports.append(_end_day(session, planner.note(session.world)))
            return reports
    finally:
        session.mutation_lock.release()


@app.get("/api/worlds/{world_id}/export")
def export(world_id: str):
    with _lock:
        world = _session(world_id).world
        return {"seed": world.seed, "day": world.day, "screens": world.screens(), "records": _records(world)}


@app.get("/api/worlds/{world_id}/replay")
def replay(world_id: str):
    with _lock:
        session = _session(world_id)
        return {"schema_version": 1, "seed": session.world.seed, "frames": _frames(session),
                "records": _records(session.world)}


def _live_brief(world: World) -> dict:
    return {"id": "live", "start_day": world.day, "days": max(1, cal.N_DAYS - world.day),
            "public_brief": "Live sandbox session started from the operations desk; no fixed "
                             "scenario or scripted horizon, just today's board."}


@app.post("/api/worlds/{world_id}/llm_day")
def llm_day(world_id: str, payload: Any = Body(None)):
    model = payload.get("model") if isinstance(payload, dict) else None
    if model is not None and not isinstance(model, str):
        raise HTTPException(400, "model must be a string")
    with _lock:
        session = _session(world_id)
        if session.world.done:
            raise HTTPException(409, "episode finished")
        if session.pending or session.screens_before is not None:
            raise HTTPException(409, "manual actions are pending for this session; end or clear the day first")
        if not session.mutation_lock.acquire(blocking=False):
            raise HTTPException(409, "another request is already mutating this session's day")
    try:
        try:
            runner._api_key()
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from None
        if session.llm_system_msg is None:
            session.llm_system_msg = {"role": "system", "content": tools.build_system_brief(_live_brief(session.world))}
        transcript_path = LIVE_RUNS_DIR / world_id / "transcript.jsonl"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(transport=_LLM_TRANSPORT) as http_client:
            frame, _fatal = runner._run_one_day(
                http_client, session.world, None, session.llm_system_msg,
                session.llm_day_blocks, session.llm_day_meta, session.world.seed,
                model or runner.MODEL, session.llm_usage, transcript_path)
        with _lock:
            session.frames.append(frame)
        return frame
    finally:
        session.mutation_lock.release()


@app.get("/api/runs")
def list_runs():
    out = []
    if RUNS_DIR.exists():
        for task_dir in sorted(p for p in RUNS_DIR.iterdir() if p.is_dir() and p.name != "live"):
            for player_dir in sorted(p for p in task_dir.iterdir() if p.is_dir()):
                run_path = player_dir / "run.json"
                if not run_path.is_file():
                    continue
                try:
                    data = json.loads(run_path.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                # Address by the directory names, not the run.json's own declared task_id/player:
                # those describe the scenario/player that produced the file and can be reused
                # across differently-named copies (e.g. CLI smoke-test runs), but GET
                # /api/runs/{task_id}/{player} resolves a path, so the two must always agree.
                out.append({"task_id": task_dir.name, "player": player_dir.name,
                            "model": data.get("model"), "status": data.get("status"),
                            "completed_days": data.get("completed_days"), "requested_days": data.get("requested_days")})
    return out


@app.get("/api/runs/{task_id}/{player}")
def get_run(task_id: str, player: str):
    if ".." in task_id or ".." in player:
        raise HTTPException(400, "invalid run reference")
    run_path = RUNS_DIR / task_id / player / "run.json"
    if not run_path.is_file():
        raise HTTPException(404, "run not found")
    data = json.loads(run_path.read_text())
    return {k: data[k] for k in RUN_FIELDS if k in data}


app.mount("/", StaticFiles(directory=Path(__file__).parents[1] / "frontend", html=True), name="frontend")
