"""Task 18: plain tool-calling model player, tested against a fake httpx transport.
Mocks verify protocol only -- they are not a model evaluation."""
import json

import httpx
import pytest

from kestrel.agent import runner


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


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(runner, "RETRY_DELAYS", (0, 0, 0))


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-super-secret-test-key")


def test_valid_action_then_end_day(tmp_path):
    transport = _sequence_transport([
        _resp(tool_calls=[_tool_call("c1", "request_audit", {"supplier": "S-SOC"})]),
        _resp(tool_calls=[_tool_call("c2", "end_day", {"note": "requested an audit"})]),
    ])
    result = runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    assert result["completed_days"] == 1
    frame = result["frames"][0]
    assert frame["status"] == "complete"
    assert frame["note"] == "requested an audit"
    assert len(frame["actions"]) == 1
    assert frame["actions"][0]["action"]["type"] == "request_audit"
    assert frame["actions"][0]["result"]["ok"] is True


def test_usage_persisted_across_requests(tmp_path):
    transport = _sequence_transport([
        _resp(tool_calls=[_tool_call("c1", "request_audit", {"supplier": "S-SOC"})],
              usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}),
        _resp(tool_calls=[_tool_call("c2", "end_day", {"note": "done"})],
              usage={"prompt_tokens": 150, "completion_tokens": 10, "total_tokens": 160}),
    ])
    result = runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    assert result["usage"] == {"prompt_tokens": 250, "completion_tokens": 30, "total_tokens": 280}
    run_json = json.loads((tmp_path / "red_sea" / "luna" / "run.json").read_text())
    assert run_json["usage"] == result["usage"]


def test_rejected_action_then_recovery(tmp_path):
    transport = _sequence_transport([
        _resp(tool_calls=[_tool_call("c1", "qualify_supplier", {"supplier": "NOT-A-SUPPLIER"})]),
        _resp(tool_calls=[_tool_call("c2", "request_audit", {"supplier": "S-SOC"})]),
        _resp(tool_calls=[_tool_call("c3", "end_day", {"note": "fixed and audited"})]),
    ])
    result = runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    frame = result["frames"][0]
    assert frame["status"] == "complete"
    assert len(frame["actions"]) == 2
    assert frame["actions"][0]["result"]["ok"] is False
    assert frame["actions"][1]["action"]["type"] == "request_audit"
    assert frame["actions"][1]["result"]["ok"] is True


def test_malformed_tool_json_continues(tmp_path):
    bad_call = {"id": "c1", "type": "function", "function": {"name": "request_audit", "arguments": "{not valid json"}}
    transport = _sequence_transport([
        _resp(tool_calls=[bad_call]),
        _resp(tool_calls=[_tool_call("c2", "end_day", {"note": "recovered from malformed json"})]),
    ])
    result = runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    frame = result["frames"][0]
    assert frame["status"] == "complete"
    assert frame["note"] == "recovered from malformed json"
    assert frame["actions"] == []  # the malformed call never reached world.apply


def test_http_failure_exhausts_retries_and_halts(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, text="internal server error")

    transport = httpx.MockTransport(handler)
    result = runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    assert len(calls) == 4  # 1 initial attempt + 3 retries
    assert result["status"] == "incomplete"
    frame = result["frames"][0]
    assert frame["status"] == "incomplete"
    assert "500" in frame["error"]


def test_cap_reached_ends_day_with_note(tmp_path):
    def handler(request):
        return httpx.Response(200, json=_resp(tool_calls=[_tool_call("c", "get_screen", {"name": "market"})]))

    transport = httpx.MockTransport(handler)
    result = runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    frame = result["frames"][0]
    assert frame["status"] == "complete"  # end_day still ran, even though the model never called the tool
    assert frame["note"] == "cap reached"


def test_resume_continues_from_checkpoint(tmp_path):
    def one_day_transport():
        return _sequence_transport([_resp(tool_calls=[_tool_call("c", "end_day", {"note": "day done"})])])

    result1 = runner.run("red_sea", "luna", days=1, transport=one_day_transport(), runs_dir=tmp_path)
    assert result1["completed_days"] == 1
    result2 = runner.run("red_sea", "luna", days=1, resume=True, transport=one_day_transport(), runs_dir=tmp_path)
    assert result2["completed_days"] == 2
    # result1's frame is still live Python objects (tuples in record history); result2's frame[0]
    # was reloaded from run.json's JSON round-trip during resume. Compare after the same round-trip.
    round_tripped = json.loads(json.dumps(result1["frames"][0], default=str))
    assert result2["frames"][0] == round_tripped


def test_request_has_no_key_or_hidden_state(tmp_path):
    transport = _sequence_transport([
        _resp(tool_calls=[_tool_call("c1", "get_screen", {"name": "market"})]),
        _resp(tool_calls=[_tool_call("c2", "end_day", {"note": "checked market"})]),
    ])
    runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    transcript = (tmp_path / "red_sea" / "luna" / "transcript.jsonl").read_text()
    assert "sk-super-secret-test-key" not in transcript
    # These are internal hidden-condition field names (kestrel.conditions/world.cond.to_dict()
    # keys), checked as JSON keys so legitimate English prose ("shipping lanes") in a task's own
    # public brief doesn't false-positive.
    for forbidden in ('"lane"', '"supplier_health"', '"port_q"', "rng_ops"):
        assert forbidden not in transcript, f"{forbidden!r} leaked into the transcript"


def test_rule_baseline_runs_via_same_cli_entrypoint(tmp_path):
    result = runner.run("red_sea", "rule", days=2, runs_dir=tmp_path)
    assert result["completed_days"] == 2
    assert result["player"] == "rule"
    assert result["model"] is None


def test_cap_reached_mid_batch_replies_to_every_tool_call(tmp_path, monkeypatch):
    # Shrink the cap so a single turn's tool_calls straddle it -- a real model can and does
    # return several tool_calls per turn (the real smoke run saw 5 and 6 in one turn).
    monkeypatch.setattr(runner, "CALL_CAP_PER_DAY", 3)
    five_calls = [_tool_call(f"c{i}", "get_screen", {"name": "market"}) for i in range(5)]
    captured = []
    responses = [
        _resp(tool_calls=five_calls),
        _resp(tool_calls=[_tool_call("d1", "end_day", {"note": "day1 done"})]),
    ]

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=responses.pop(0))

    transport = httpx.MockTransport(handler)
    result = runner.run("red_sea", "luna", days=2, transport=transport, runs_dir=tmp_path)
    assert result["completed_days"] == 2
    assert result["frames"][0]["note"] == "cap reached"

    # The next request (day 1) still carries day 0's assistant tool_calls message (kept
    # verbatim -- only 1 day so far, well under the trim threshold). Every one of its
    # tool_call ids must have a matching role:"tool" reply among the sent messages, including
    # the 2 that were never actually executed because the cap was hit mid-batch.
    day1_messages = captured[1]["messages"]
    assistant_msgs = [m for m in day1_messages if m.get("role") == "assistant" and m.get("tool_calls")]
    assert len(assistant_msgs) == 1
    tool_call_ids = {tc["id"] for tc in assistant_msgs[0]["tool_calls"]}
    assert tool_call_ids == {f"c{i}" for i in range(5)}
    tool_reply_ids = {m["tool_call_id"] for m in day1_messages if m.get("role") == "tool"}
    assert tool_call_ids <= tool_reply_ids


def test_resume_rejects_mismatched_task_id(tmp_path):
    transport = _sequence_transport([_resp(tool_calls=[_tool_call("c", "end_day", {"note": "day0"})])])
    runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    foreign_dir = tmp_path / "cny_prebuild" / "luna"
    foreign_dir.mkdir(parents=True)
    foreign_run_path = foreign_dir / "run.json"
    foreign_run_path.write_text((tmp_path / "red_sea" / "luna" / "run.json").read_text())
    before = foreign_run_path.read_text()

    def unexpected_call(request):
        raise AssertionError("resume should stop before sending any request")

    with pytest.raises(ValueError, match="task_id"):
        runner.run("cny_prebuild", "luna", days=1, resume=True, transport=httpx.MockTransport(unexpected_call), runs_dir=tmp_path)
    assert foreign_run_path.read_text() == before  # never touched


def test_resume_rejects_stale_source_hash(tmp_path):
    transport = _sequence_transport([_resp(tool_calls=[_tool_call("c", "end_day", {"note": "day0"})])])
    runner.run("red_sea", "luna", days=1, transport=transport, runs_dir=tmp_path)
    run_path = tmp_path / "red_sea" / "luna" / "run.json"
    data = json.loads(run_path.read_text())
    data["source_hash"] = "0" * 12
    run_path.write_text(json.dumps(data))
    before = run_path.read_text()

    def unexpected_call(request):
        raise AssertionError("resume should stop before sending any request")

    with pytest.raises(ValueError, match="source_hash"):
        runner.run("red_sea", "luna", days=1, resume=True, transport=httpx.MockTransport(unexpected_call), runs_dir=tmp_path)
    assert run_path.read_text() == before  # never touched
