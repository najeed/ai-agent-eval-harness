import pytest
import json
import asyncio
from pathlib import Path
from eval_runner.trace_recorder import record_interaction


@pytest.mark.asyncio
async def test_record_interaction_flow(tmp_path, monkeypatch, adapter_stub, capsys):
    """Test the full flow of record_interaction with a real local server stub."""
    # 1. Setup paths and input sequence
    monkeypatch.chdir(tmp_path)
    server = adapter_stub
    agent_url = f"http://{server.host}:{server.port}/execute_task"

    # Mock 'input' to return a task then 'exit'
    inputs = ["Tell me a joke", "exit"]
    def mock_input(_):
        if not inputs:
            return "exit"
        return inputs.pop(0)
    monkeypatch.setattr("builtins.input", mock_input)

    # Execute
    await record_interaction(agent_url)

    # 2. Verify results
    runs_dir = tmp_path / "runs"
    assert runs_dir.exists()

    log_file = list(runs_dir.glob("run-*.jsonl"))[0]
    assert log_file.exists()

    with open(log_file, "r") as f:
        events = [json.loads(line) for line in f]

    # Expected events: run_start, agent_request, agent_response
    event_types = [e["event"] for e in events]
    assert "run_start" in event_types
    assert "agent_request" in event_types
    assert "agent_response" in event_types

    # Verify content of agent_request
    request_event = next(e for e in events if e["event"] == "agent_request")
    assert request_event["task"] == "Tell me a joke"

    # Verify content of agent_response (adapter response format)
    response_event = next(e for e in events if e["event"] == "agent_response")
    # Note: record_interaction extracts summary/content correctly from stub
    assert "This is a joke" in str(response_event["content"])


@pytest.mark.asyncio
async def test_record_interaction_error(tmp_path, monkeypatch, capsys):
    """Test error handling in record_interaction with real connection failure."""
    monkeypatch.chdir(tmp_path)
    # Use a non-existent port to trigger connection failure
    agent_url = "http://localhost:65534/execute_task"

    # Mock 'input' to return a task then 'exit'
    inputs = ["Break it", "exit"]
    def mock_input(_):
        if not inputs:
            return "exit"
        return inputs.pop(0)
    monkeypatch.setattr("builtins.input", mock_input)

    await record_interaction(agent_url)

    # Verify error message was printed to stdout/stderr
    captured = capsys.readouterr().out
    assert "Error: Failed to contact agent" in captured
