"""OpenRouter chat-completions client and the per-day tool-calling loop for the 'luna'
model player, plus a matching runner for the 'rule' baseline (Task 18).
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import tools
from .tasks import SOURCE_HASH, TASKS, build_frame, evidence, make_event_driver, prepare_task, rule_day
from ..screens import record_view

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-5.6-luna"
MAX_TOKENS = 4096
CALL_CAP_PER_DAY = 40
RETRY_DELAYS = (1, 3, 9)
TIMEOUT_S = 60.0
TRIM_THRESHOLD = 60
KEEP_VERBATIM_DAYS = 2

RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parents[2] / ".env"  # supplychain/.env
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("OPENROUTER_API_KEY not set in environment or supplychain/.env")


def _append_transcript(path: Path, day, request: dict, response, error) -> None:
    line = {"ts": _now_iso(), "day": day, "request": request, "response": response, "error": error}
    with open(path, "a") as f:
        f.write(json.dumps(line, default=str) + "\n")


def _accumulate_usage(totals: dict, usage: dict | None) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, (int, float)):
            totals[k] = totals.get(k, 0) + v


def chat_completion(http_client: httpx.Client, messages: list, seed: int, model: str = MODEL, max_tokens: int = MAX_TOKENS):
    """POST one chat-completions request with retries. Returns (response_json, error, parameters)."""
    parameters = {"model": model, "seed": seed, "max_tokens": max_tokens, "tool_choice": "auto"}
    payload = {**parameters, "messages": messages, "tools": tools.tool_schemas()}
    headers = {"Authorization": f"Bearer {_api_key()}"}
    last_error = None
    for delay in (0,) + RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            resp = http_client.post(OPENROUTER_URL, json=payload, headers=headers, timeout=TIMEOUT_S)
        except httpx.TimeoutException as e:
            last_error = f"timeout: {e}"
            continue
        except httpx.HTTPError as e:
            last_error = f"http error: {e}"
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
            continue
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:500]}", parameters
        return resp.json(), None, parameters
    return None, last_error, parameters


def _flatten(system_msg: dict, day_blocks: list) -> list:
    msgs = [system_msg]
    for block in day_blocks:
        msgs.extend(block)
    return msgs


def _summarize_day(meta: dict) -> dict:
    return {"role": "user", "content": f"[Day {meta['day']} summary: {meta['n_calls']} tool call(s), "
                                        f"status={meta['status']}, note={meta['note']!r}]"}


def _maybe_trim(day_blocks: list, day_meta: list) -> None:
    total = 1 + sum(len(b) for b in day_blocks)
    if total <= TRIM_THRESHOLD:
        return
    for i in range(len(day_blocks) - KEEP_VERBATIM_DAYS):
        if day_meta[i].get("collapsed"):
            continue
        day_blocks[i] = [_summarize_day(day_meta[i])]
        day_meta[i]["collapsed"] = True


def _opening_message(world) -> dict:
    scr = world.screens()
    opening = {"calendar": scr["calendar"], "market": scr["market"], "finance": scr["finance"],
               "exceptions": scr["exceptions"], "news": scr["news"]}
    from .. import calendar as cal
    header = f"Day {world.day} morning ({cal.to_date(world.day).isoformat()}). Call get_screen for anything else you need."
    return {"role": "user", "content": header + "\n" + json.dumps(opening, default=str)}


def _run_one_day(http_client, world, event_driver, system_msg, day_blocks, day_meta, seed, model, usage_totals, transcript_path):
    """Play one day of tool calls. Returns (frame, fatal_error_or_None)."""
    day = world.day
    screens_before = world.screens()
    day_blocks.append([_opening_message(world)])
    day_meta.append({"day": day, "n_calls": 0, "note": "", "status": "in_progress"})

    actions_log, ended, calls_made, fatal = [], False, 0, None
    while not ended and calls_made < CALL_CAP_PER_DAY:
        messages = _flatten(system_msg, day_blocks)
        resp, err, parameters = chat_completion(http_client, messages, seed, model)
        _append_transcript(transcript_path, day, {"messages": messages, **parameters}, resp, err)
        if err:
            fatal = err
            break
        usage = resp.get("usage", {})
        _accumulate_usage(usage_totals, usage)
        choice = resp["choices"][0]
        msg = choice["message"]
        day_blocks[-1].append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls")})
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            day_blocks[-1].append({"role": "user", "content": "Call a tool to act, or end_day(note=...) if you are done for today."})
            calls_made += 1
            continue
        for tc in tool_calls:
            if calls_made >= CALL_CAP_PER_DAY:
                # Still reply to every remaining tool_call id in this turn -- an assistant
                # tool_calls message with any unanswered id makes the next request malformed
                # (OpenAI-compatible APIs reject it, and it would otherwise get silently
                # replayed into a later day's messages via day_blocks/_maybe_trim).
                result = {"ok": False, "reason": "daily tool-call cap reached", "id": None}
                day_blocks[-1].append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, default=str)})
                continue
            calls_made += 1
            name = tc["function"]["name"]
            args, parse_err = tools.parse_tool_arguments(tc["function"].get("arguments", ""))
            if parse_err:
                result = {"ok": False, "reason": parse_err, "id": None}
            elif name not in tools.TOOL_NAMES:
                result = {"ok": False, "reason": f"unknown tool {name!r}", "id": None}
            elif name == "end_day":
                day_meta[-1]["note"] = args.get("note", "")
                ended = True
                result = {"ok": True, "reason": "", "id": None}
            else:
                result = tools.call_tool(world, name, args)
                if name in tools.ENGINE_TOOLS:
                    actions_log.append(({"type": name, **args}, result))
            day_blocks[-1].append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, default=str)})
            if ended:
                break

    day_meta[-1]["n_calls"] = calls_made
    if fatal is not None:
        day_meta[-1]["status"] = "incomplete"
        note = day_meta[-1]["note"]
        frame = build_frame(day, screens_before["calendar"]["date"], screens_before,
                             [a for a, _ in actions_log], [r for _, r in actions_log],
                             note, None, None, "incomplete", fatal)
        return frame, fatal

    note = day_meta[-1]["note"] if ended else "cap reached"
    day_meta[-1]["note"] = note
    if event_driver is not None:
        event_driver(world)
    report = world.end_day()
    screens_after = world.screens()
    day_meta[-1]["status"] = "complete"
    _maybe_trim(day_blocks, day_meta)
    frame = build_frame(day, report["date"], screens_before, [a for a, _ in actions_log], [r for _, r in actions_log],
                         note, report, screens_after, "complete", None)
    return frame, None


def _prepare_or_resume(task_id: str, run_path: Path):
    world, brief = prepare_task(task_id)
    driver = make_event_driver(task_id)
    prior_run = None
    if run_path.exists():
        prior_run = json.loads(run_path.read_text())
        spec = TASKS[task_id]
        if (prior_run.get("task_id") != task_id or prior_run.get("task_version") != spec["version"]
                or prior_run.get("source_hash") != SOURCE_HASH):
            raise ValueError(
                f"cannot resume {run_path}: checkpoint is for task_id={prior_run.get('task_id')!r} "
                f"task_version={prior_run.get('task_version')!r} source_hash={prior_run.get('source_hash')!r}, "
                f"but resuming task_id={task_id!r} task_version={spec['version']!r} source_hash={SOURCE_HASH!r}"
            )
        for frame in prior_run["frames"]:
            if frame["status"] != "complete":
                break
            for entry in frame["actions"]:
                world.apply(entry["action"])
            driver(world)
            world.end_day()
    return world, brief, driver, prior_run


def _write_run(run_path: Path, result: dict) -> None:
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps(result, default=str))


def _base_result(task_id, player, model, parameters, started_at, brief, frames, usage, world) -> dict:
    spec = TASKS[task_id]
    return {
        "schema_version": 1, "run_id": f"{task_id}-{player}-{spec['seed']}", "task_id": task_id,
        "task_version": spec["version"], "source_hash": SOURCE_HASH, "player": player, "model": model,
        "parameters": parameters, "started_at": started_at, "initial_day": brief["start_day"],
        "requested_days": spec["days"], "completed_days": len(frames),
        "status": "complete" if len(frames) == spec["days"] else "incomplete",
        "usage": usage, "frames": frames,
        "records": {rid: record_view(world.records.get(rid)) for rid in world.records.ids()},
        # D2: persisted so evidence() is queryable from the run.json artifact itself, without
        # re-executing the simulation (see docs/model-findings.md D2). Recomputed at every
        # checkpoint write; the version present once status=="complete" is the run's final evidence.
        "evidence": evidence(world, task_id),
    }


def _run_rule(task_id: str, days, resume: bool, run_path: Path) -> dict:
    spec = TASKS[task_id]
    if resume and run_path.exists():
        world, brief, driver, prior_run = _prepare_or_resume(task_id, run_path)
        frames, started_at = prior_run["frames"], prior_run["started_at"]
    else:
        world, brief = prepare_task(task_id)
        driver = make_event_driver(task_id)
        frames, started_at = [], _now_iso()

    days_to_run = (spec["days"] - len(frames)) if days is None else days
    result = _base_result(task_id, "rule", None, {}, started_at, brief, frames, {}, world)
    for _ in range(max(0, days_to_run)):
        if world.done or len(frames) >= spec["days"]:
            break
        frames.append(rule_day(world, driver))
        result = _base_result(task_id, "rule", None, {}, started_at, brief, frames, {}, world)
        _write_run(run_path, result)
    return result


def _run_luna(task_id: str, days, resume: bool, run_path: Path, transcript_path: Path, model: str, transport=None) -> dict:
    spec = TASKS[task_id]
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    if resume and run_path.exists():
        world, brief, driver, prior_run = _prepare_or_resume(task_id, run_path)
        frames, usage_totals, started_at = prior_run["frames"], prior_run["usage"], prior_run["started_at"]
        parameters = prior_run.get("parameters", {})
    else:
        world, brief = prepare_task(task_id)
        driver = make_event_driver(task_id)
        frames, usage_totals, started_at, parameters = [], {}, _now_iso(), {}

    system_msg = {"role": "system", "content": tools.build_system_brief(brief)}
    day_blocks: list = []
    day_meta: list = []
    days_to_run = (spec["days"] - len(frames)) if days is None else days

    result = _base_result(task_id, "luna", model, parameters, started_at, brief, frames, usage_totals, world)
    with httpx.Client(transport=transport) as http_client:
        for _ in range(max(0, days_to_run)):
            if world.done or len(frames) >= spec["days"]:
                break
            frame, fatal = _run_one_day(http_client, world, driver, system_msg, day_blocks, day_meta,
                                         spec["seed"], model, usage_totals, transcript_path)
            frames.append(frame)
            if fatal is None:
                # record the effective parameters of the last successful request
                pass
            result = _base_result(task_id, "luna", model, parameters or {"model": model, "seed": spec["seed"],
                                   "max_tokens": MAX_TOKENS, "tool_choice": "auto"}, started_at, brief, frames, usage_totals, world)
            _write_run(run_path, result)
            if fatal is not None:
                break
    return result


def run(task_id: str, player: str, days: int | None = None, resume: bool = False, model: str = MODEL,
        transport=None, runs_dir: Path | None = None) -> dict:
    if task_id not in TASKS:
        raise ValueError(f"unknown task {task_id!r}")
    out_dir = (runs_dir or RUNS_DIR) / task_id / player
    run_path = out_dir / "run.json"
    if player == "rule":
        return _run_rule(task_id, days, resume, run_path)
    if player == "luna":
        return _run_luna(task_id, days, resume, run_path, out_dir / "transcript.jsonl", model, transport=transport)
    raise ValueError(f"unknown player {player!r}")
