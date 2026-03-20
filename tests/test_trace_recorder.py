import pytest
import json
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
from eval_runner.trace_recorder import record_interaction


@pytest.mark.asyncio
async def test_record_interaction_flow(tmp_path, monkeypatch):
    """Test the full flow of record_interaction with mocks."""
    # 1. Setup paths and mocks
    monkeypatch.chdir(tmp_path)
    agent_url = "http://localhost:5001/execute_task"

    # Mock 'input' to return a task then 'exit'
    inputs = ["Tell me a joke", "exit"]
    input_mock = MagicMock(side_effect=inputs)

    # Mock aiohttp ClientSession and response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.get_json = AsyncMock(
        return_value={"summary": "This is a joke", "action": "final_answer"}
    )
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("builtins.input", input_mock), patch(
        "aiohttp.ClientSession", return_value=mock_session
    ):

        # We need to handle the infinite loop and the fact that record_interaction
        # might print things we want to suppress or capture.
        with patch("builtins.print"):
            await record_interaction(agent_url)

    # 2. Verify results
    # Check if a log file was created in 'runs'
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

    # Verify content of agent_response
    response_event = next(e for e in events if e["event"] == "agent_response")
    assert response_event["content"]["summary"] == "This is a joke"


@pytest.mark.asyncio
async def test_record_interaction_error(tmp_path, monkeypatch):
    """Test error handling in record_interaction."""
    monkeypatch.chdir(tmp_path)
    agent_url = "http://localhost:5001/execute_task"

    # Mock 'input' to return a task then 'exit'
    inputs = ["Break it", "exit"]
    input_mock = MagicMock(side_effect=inputs)

    # Mock aiohttp to raise an exception
    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=Exception("Connection failed"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("builtins.input", input_mock), patch(
        "aiohttp.ClientSession", return_value=mock_session
    ), patch("builtins.print") as mock_print:

        await record_interaction(agent_url)

        # Verify error message was printed
        mock_print.assert_any_call(
            "  ❌ Error: Failed to contact agent: Connection failed"
        )
