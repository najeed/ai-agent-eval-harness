"""
Consolidated Trace & Flight Recorder Test Suite for AgentV Evaluation Harness.
Verifies trace recording, flight recorder plugins (vault rotation, fallback),
trace utilities (JSON/JSONL), and result reconstruction.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import cli, trace_recorder, trace_utils
from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin as FlightRecorder

# --- 1. Trace Recorder & Masking ---


@pytest.mark.asyncio
async def test_record_interaction_masking(tmp_path, monkeypatch):
    """Test sensitive data masking in recorded traces."""
    inputs = ["mask_me", "exit"]
    monkeypatch.setattr("builtins.input", lambda _: inputs.pop(0))
    monkeypatch.setattr("eval_runner.trace_recorder.Path", lambda *args: tmp_path)

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"token": "secret_12345678901234567890"})  # > 20 chars

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    with patch("aiohttp.ClientSession.post", return_value=ctx):
        await trace_recorder.record_interaction("http://fake")

    log_file = list(tmp_path.glob("run-*.jsonl"))[0]
    assert "secr...[MASKED]" in log_file.read_text()


# --- 2. Flight Recorder (Vault & Rotation) ---


def test_flight_recorder_lifecycle(tmp_path):
    fr = FlightRecorder()
    fr.log_dir = tmp_path

    # 1. Start Run
    fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": "r1"}))
    assert fr.master_log_path.exists()

    # 2. Finalize
    fr.finalize_run()

    # 3. Rotate (Smoke)
    fr.rotate_logs()


def test_flight_recorder_error_handling(tmp_path, capsys):
    fr = FlightRecorder()
    fr.log_dir = tmp_path

    with patch("builtins.open", side_effect=OSError("Access Denied")):
        fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": "r1"}))

    assert "File I/O Error" in capsys.readouterr().err


# --- 3. Trace Utilities & Fallback ---


def test_load_events_and_reconstruct():
    events = [
        {"task_id": "T1", "event": "evaluation", "metric": "s", "value": 1.0, "success": True},
        {"task_id": "T1", "event": "agent_response", "content": "hi"},
    ]
    results = trace_utils.reconstruct_results_from_events(events)
    assert len(results) == 1
    assert results[0]["metrics"][0]["score"] == 1.0


def test_replay_vault_fallback(tmp_path, monkeypatch, capsys):
    """Verify fallback from Vault to Master Log."""
    monkeypatch.chdir(tmp_path)
    run_id = "fallback-run"

    # Setup Master Log
    master_log = tmp_path / "run.jsonl"
    master_log.write_text(
        json.dumps({"event": "run_start", "run_id": run_id, "scenario": "s1"}) + "\n"
    )

    with patch("eval_runner.config.RUN_LOG_DIR", tmp_path):
        with patch("sys.argv", ["agentv", "replay", "--run-id", run_id]):
            with pytest.raises(SystemExit) as e:
                cli.main()
            assert e.value.code == 0
            out = capsys.readouterr().out
            assert "Falling back to master log" in out
            assert "--- Run Started: fallback-run" in out


# === Ported edge-case coverage ===


def test_aes_json_encoder_types(tmp_path):
    """Test AESJsonEncoder with Path, datetime, date, Mock, and fallback types."""
    import datetime

    from eval_runner.trace_utils import AESJsonEncoder

    encoder = AESJsonEncoder()

    # Path
    p = tmp_path / "test"
    assert encoder.default(p) == str(p)

    # datetime
    dt = datetime.datetime(2026, 4, 15, 12, 0, tzinfo=datetime.UTC)
    assert encoder.default(dt) == dt.isoformat()

    # date
    d = datetime.date(2026, 4, 15)
    assert encoder.default(d) == d.isoformat()

    # MagicMock
    mock_obj = MagicMock(_mock_name="test_mock")
    assert "Mock" in encoder.default(mock_obj)

    # Fallback to str
    class Unserializable:
        def __str__(self):
            return "unserializable_obj"

    assert encoder.default(Unserializable()) == "unserializable_obj"


def test_load_events_file_not_found():
    """Verify FileNotFoundError is raised for missing files."""
    from eval_runner.trace_utils import load_events

    with pytest.raises(FileNotFoundError):
        load_events("non_existent_file.jsonl")


def test_load_events_formats(tmp_path):
    """Test load_events with JSONL, JSON array, single object, and malformed inputs."""
    from eval_runner.trace_utils import load_events

    # Standard JSONL
    f1 = tmp_path / "f1.jsonl"
    f1.write_text('{"event": "start"}\n{"event": "stop"}')
    assert len(load_events(f1)) == 2

    # JSON array
    f2 = tmp_path / "f2.json"
    f2.write_text('[{"event": "start"}, {"event": "stop"}]')
    assert len(load_events(f2)) == 2

    # Single JSON object
    f3 = tmp_path / "f3.json"
    f3.write_text('{"event": "start"}')
    assert len(load_events(f3)) == 1

    # Empty file
    f4 = tmp_path / "f4.json"
    f4.write_text("   ")
    assert load_events(f4) == []

    # Malformed lines (valid lines retained)
    f5 = tmp_path / "f5.jsonl"
    f5.write_text('{"event": "start"}\n{invalid_json}\n{"event": "end"}')
    events = load_events(f5)
    assert len(events) == 2

    # Corrupt JSON-like but no valid events
    f6 = tmp_path / "f6.json"
    f6.write_text("invalid data\nmore junk")
    with pytest.raises(ValueError, match="No valid JSON events"):
        load_events(f6)


def test_reconstruct_results_full(tmp_path):
    """Test reconstruction with evaluation, agent, and tool events."""
    from eval_runner.trace_utils import reconstruct_results_from_events

    events = [
        {"task_id": "T1", "event": "evaluation", "metric": "safety", "value": 0.9, "success": True},
        {"task_id": "T1", "event": "agent_response", "content": "I am an agent"},
        {"task_id": "T1", "event": "tool_result", "tool": "search", "status": "success"},
    ]
    results = reconstruct_results_from_events(events)
    assert len(results) == 1
    res = results[0]
    assert res["task_id"] == "T1"
    assert res["metrics"][0]["score"] == 0.9
    assert res["conversation_history"][0]["role"] == "agent"
    assert res["conversation_history"][1]["role"] == "user"


@pytest.mark.asyncio
async def test_record_interaction_error_path(tmp_path, monkeypatch):
    """Test that HTTP 500 errors are logged but not recorded as responses."""

    from eval_runner.trace_recorder import record_interaction

    inputs = ["task1", "exit"]
    monkeypatch.setattr("builtins.input", lambda _: inputs.pop(0))
    monkeypatch.setattr("eval_runner.trace_recorder.Path", lambda *args, **kwargs: tmp_path)

    mock_resp = MagicMock()
    mock_resp.status = 500
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    ctx.__aexit__ = AsyncMock()

    with patch("aiohttp.ClientSession.post", return_value=ctx):
        await record_interaction("http://fake-agent")

    files = list(tmp_path.glob("run-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    # Should have: run_start + agent_request (no response on 500)
    assert len(lines) == 2


def test_trace_recorder_main_block(monkeypatch):
    """Test the __main__ block of trace_recorder."""
    import runpy
    import sys

    mock_run = MagicMock()
    monkeypatch.setattr("asyncio.run", mock_run)

    with patch.object(sys, "argv", ["trace_recorder.py", "http://custom-url"]):
        sys.modules.pop("eval_runner.trace_recorder", None)
        runpy.run_module("eval_runner.trace_recorder", run_name="__main__")

    mock_run.assert_called_once()
    coro = mock_run.call_args[0][0]
    coro.close()


@pytest.mark.asyncio
async def test_record_interaction_list_masking(tmp_path, monkeypatch):
    """Test that list values are recursively masked in trace_recorder."""
    from eval_runner.trace_recorder import record_interaction

    inputs = ["mask_me", "exit"]
    monkeypatch.setattr("builtins.input", lambda _: inputs.pop(0))
    monkeypatch.setattr("eval_runner.trace_recorder.Path", lambda *args, **kwargs: tmp_path)

    # Return a list payload containing a secret token
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "summary": "done",
            "items": [{"api_secret_very_long_key": "secret_longerthan20chars_shouldbmasked"}],
        }
    )
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    ctx.__aexit__ = AsyncMock()

    with patch("aiohttp.ClientSession.post", return_value=ctx):
        await record_interaction("http://fake-agent")

    log_file = list(tmp_path.glob("run-*.jsonl"))[0]
    content = log_file.read_text()
    assert "[MASKED]" in content


@pytest.mark.asyncio
async def test_record_interaction_connection_exception(tmp_path, monkeypatch):
    """Test that connection exceptions are caught and printed."""
    from eval_runner.trace_recorder import record_interaction

    inputs = ["crash_task", "exit"]
    monkeypatch.setattr("builtins.input", lambda _: inputs.pop(0))
    monkeypatch.setattr("eval_runner.trace_recorder.Path", lambda *args, **kwargs: tmp_path)

    with patch("aiohttp.ClientSession.post", side_effect=Exception("Connection Refused")):
        await record_interaction("http://fake-agent")

    files = list(tmp_path.glob("run-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip().splitlines()
    # run_start + agent_request only (exception prevents response)
    assert len(content) == 2
