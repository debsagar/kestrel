import json

import httpx
from fastapi.testclient import TestClient
import pytest

from kestrel import api
from kestrel.agent import runner
from kestrel.api import _sessions, app


@pytest.fixture(autouse=True)
def clean_sessions():
    _sessions.clear()
    yield
    _sessions.clear()


def _resp(content=None, tool_calls=None, usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def _tool_call(call_id, name, arguments):
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def _sequence_transport(responses):
    queue = list(responses)

    def handler(request):
        return httpx.Response(200, json=queue.pop(0))

    return httpx.MockTransport(handler)


def test_world_lifecycle_and_public_replay():
    client = TestClient(app)
    world_id = client.post("/api/worlds", json={"seed": 1}).json()["id"]
    assert "inventory" in client.get(f"/api/worlds/{world_id}/screens").json()

    results = client.post(f"/api/worlds/{world_id}/actions", json=[{"type": "teleport"}, "bad"]).json()
    assert [result["ok"] for result in results] == [False, False]
    partial = client.get(f"/api/worlds/{world_id}/replay").json()["frames"]
    assert len(partial) == 1 and partial[0]["status"] == "incomplete" and partial[0]["report"] is None
    assert client.post(f"/api/worlds/{world_id}/end_day", json={"note": "manual"}).json()["day"] == 0
    assert len(client.post(f"/api/worlds/{world_id}/autopilot?days=2").json()) == 2

    replay = client.get(f"/api/worlds/{world_id}/replay").json()
    assert len(replay["frames"]) == 3
    frame = replay["frames"][0]
    assert set(frame) == {"day", "date", "screens_before", "actions", "note", "report",
                          "screens_after", "status", "error"}
    assert len(frame["actions"]) == 2 and frame["note"] == "manual"
    exported = client.get(f"/api/worlds/{world_id}/export").json()
    assert "hidden" not in exported and "screens" in exported and "records" in exported


def test_strict_inputs_and_static_placeholder():
    client = TestClient(app)
    assert client.post("/api/worlds", json={"seed": True}).status_code == 400
    world_id = client.post("/api/worlds", json={"seed": 2}).json()["id"]
    assert client.post(f"/api/worlds/{world_id}/autopilot?days=1.0").status_code == 400
    rejected = client.post(f"/api/worlds/{world_id}/actions", json={"type": "teleport"}).json()
    assert rejected[0]["ok"] is False
    bad_int = client.post(f"/api/worlds/{world_id}/actions", json=[{
        "type": "create_po", "supplier": "S-SOC", "component": "SOC", "qty": 2000,
        "requested_day": "30",
    }]).json()
    assert bad_int[0]["ok"] is False and "integer" in bad_int[0]["reason"]
    assert "Kestrel" in client.get("/").text


def test_list_and_get_run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(api, "RUNS_DIR", tmp_path)
    result = runner.run("red_sea", "rule", days=1, runs_dir=tmp_path)
    assert result["completed_days"] == 1
    # A differently-named copy of the same task_id, as the CLI's smoke-test runs are:
    # /api/runs must key off the directory name it can actually be fetched back by,
    # not the run.json's own declared task_id (which both copies share).
    (tmp_path / "_smoke_red_sea_1day" / "rule").mkdir(parents=True)
    (tmp_path / "_smoke_red_sea_1day" / "rule" / "run.json").write_text((tmp_path / "red_sea" / "rule" / "run.json").read_text())

    client = TestClient(app)
    runs = client.get("/api/runs").json()
    keys = [{k: r[k] for k in ("task_id", "player", "status", "completed_days", "requested_days", "model")} for r in runs]
    assert {"task_id": "red_sea", "player": "rule", "status": "incomplete",
            "completed_days": 1, "requested_days": 45, "model": None} in keys
    assert {"task_id": "_smoke_red_sea_1day", "player": "rule", "status": "incomplete",
            "completed_days": 1, "requested_days": 45, "model": None} in keys

    fetched = client.get("/api/runs/red_sea/rule").json()
    assert fetched["completed_days"] == 1 and fetched["frames"][0]["status"] == "complete"
    assert "transcript" not in fetched and fetched["source_hash"]  # provenance is public
    assert client.get("/api/runs/_smoke_red_sea_1day/rule").status_code == 200

    assert client.get("/api/runs/nope/rule").status_code == 404
    assert client.get("/api/runs/../etc/rule").status_code in (400, 404)


def test_llm_day_missing_key_returns_503(monkeypatch):
    def _raise():
        raise RuntimeError("OPENROUTER_API_KEY not set in environment or supplychain/.env")
    monkeypatch.setattr(runner, "_api_key", _raise)

    client = TestClient(app)
    world_id = client.post("/api/worlds", json={"seed": 1}).json()["id"]
    resp = client.post(f"/api/worlds/{world_id}/llm_day")
    assert resp.status_code == 503
    assert "OPENROUTER_API_KEY" in resp.json()["detail"]


def test_llm_day_runs_same_protocol_as_cli(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    transport = _sequence_transport([
        _resp(tool_calls=[_tool_call("c1", "request_audit", {"supplier": "S-SOC"})]),
        _resp(tool_calls=[_tool_call("c2", "end_day", {"note": "audited SOC"})]),
    ])
    monkeypatch.setattr(api, "_LLM_TRANSPORT", transport)

    client = TestClient(app)
    world_id = client.post("/api/worlds", json={"seed": 1}).json()["id"]
    frame = client.post(f"/api/worlds/{world_id}/llm_day").json()
    assert frame["status"] == "complete"
    assert frame["note"] == "audited SOC"
    assert len(frame["actions"]) == 1
    assert frame["actions"][0]["action"]["type"] == "request_audit"
    assert frame["actions"][0]["result"]["ok"] is True

    replay = client.get(f"/api/worlds/{world_id}/replay").json()
    assert len(replay["frames"]) == 1 and replay["frames"][0]["note"] == "audited SOC"


def test_llm_day_rejects_concurrent_mutation(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    client = TestClient(app)
    world_id = client.post("/api/worlds", json={"seed": 1}).json()["id"]
    session = api._session(world_id)
    assert session.mutation_lock.acquire(blocking=False)
    try:
        resp = client.post(f"/api/worlds/{world_id}/llm_day")
        assert resp.status_code == 409
    finally:
        session.mutation_lock.release()


def test_actions_rejects_while_mutation_lock_held(monkeypatch):
    """The mutation_lock guards every day-mutating route, not just llm_day: a lock held
    (e.g. by an in-flight llm_day's network loop) must also make /actions and /end_day
    refuse with 409, since both can otherwise race a concurrent world.apply/end_day."""
    client = TestClient(app)
    world_id = client.post("/api/worlds", json={"seed": 1}).json()["id"]
    session = api._session(world_id)
    assert session.mutation_lock.acquire(blocking=False)
    try:
        resp = client.post(f"/api/worlds/{world_id}/actions", json=[{"type": "teleport"}])
        assert resp.status_code == 409
        resp = client.post(f"/api/worlds/{world_id}/end_day", json={"note": ""})
        assert resp.status_code == 409
        resp = client.post(f"/api/worlds/{world_id}/autopilot?days=1")
        assert resp.status_code == 409
    finally:
        session.mutation_lock.release()

    # released, the same session's routes work normally again
    assert client.post(f"/api/worlds/{world_id}/actions", json=[{"type": "teleport"}]).status_code == 200


def test_llm_day_rejects_when_manual_actions_pending(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    client = TestClient(app)
    world_id = client.post("/api/worlds", json={"seed": 1}).json()["id"]
    client.post(f"/api/worlds/{world_id}/actions", json=[{"type": "teleport"}])
    resp = client.post(f"/api/worlds/{world_id}/llm_day")
    assert resp.status_code == 409
