import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.trace_recorder import record_interaction


@pytest.fixture
def mock_aiohttp_session():
    with patch("aiohttp.ClientSession") as mock_session_class:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_class.return_value = mock_session
        yield mock_session


def test_record_interaction_masking_and_errors(tmp_path, monkeypatch, mock_aiohttp_session):
    """Test trace_recorder masking logic, error paths, and normal operation."""
    # 1. Setup inputs: a normal task, a task triggering error, and exit
    inputs = ["task1", "task2", "exit"]

    def mock_input(prompt):
        return inputs.pop(0)

    monkeypatch.setattr("builtins.input", mock_input)
    monkeypatch.setattr("eval_runner.trace_recorder.Path", lambda *args, **kwargs: tmp_path)

    # 2. Setup mock responses
    # First response: 200 OK, with data to mask (dict, list, sensitive string > 20 chars)
    mock_resp_1 = MagicMock()
    mock_resp_1.status = 200
    long_secret = "secret_12345678901234567890"  # > 20 chars, contains "secret"
    mock_resp_1.json = AsyncMock(
        return_value={
            "summary": "Success",
            "nested": {"key1": "val1"},
            "list_data": [{"item": "a"}],
            "sensitive_token": long_secret,
            "token_short": "token_123",  # contains token but <= 20 chars
        }
    )

    # Second response: 500 Error
    mock_resp_2 = MagicMock()
    mock_resp_2.status = 500

    # Wrap them in Async context managers
    ctx_1 = MagicMock()
    ctx_1.__aenter__ = AsyncMock(return_value=mock_resp_1)
    ctx_1.__aexit__ = AsyncMock()

    ctx_2 = MagicMock()
    ctx_2.__aenter__ = AsyncMock(return_value=mock_resp_2)
    ctx_2.__aexit__ = AsyncMock()

    mock_aiohttp_session.post.side_effect = [ctx_1, ctx_2]

    # Run the function
    asyncio.run(record_interaction("http://fake-agent"))

    # Verify saved file
    files = list(tmp_path.glob("run-*.jsonl"))
    assert len(files) == 1

    content = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 4  # start, req1, res1, req2  (res2 not added due to 500)

    start_ev = json.loads(content[0])
    assert start_ev["event"] == "run_start"

    req1 = json.loads(content[1])
    assert req1["event"] == "agent_request"
    assert req1["task"] == "task1"

    res1 = json.loads(content[2])
    assert res1["event"] == "agent_response"
    # Check masking
    data = res1["content"]
    assert data["sensitive_token"] == "secr...[MASKED]"
    assert data["token_short"] == "token_123"
    assert data["nested"]["key1"] == "val1"
    assert data["list_data"][0]["item"] == "a"

    req2 = json.loads(content[3])
    assert req2["event"] == "agent_request"
    assert req2["task"] == "task2"


def test_record_interaction_exception(tmp_path, monkeypatch, mock_aiohttp_session):
    """Test exception during agent communication."""
    inputs = ["crash_task", "exit"]
    monkeypatch.setattr("builtins.input", lambda p: inputs.pop(0))
    monkeypatch.setattr("eval_runner.trace_recorder.Path", lambda *args, **kwargs: tmp_path)

    mock_aiohttp_session.post.side_effect = Exception("Connection Refused")

    asyncio.run(record_interaction("http://fake-agent"))

    # Should save the start event and the request, but no response
    files = list(tmp_path.glob("run-*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 2


def test_trace_recorder_main(monkeypatch):
    """Test the __main__ block logic."""
    import runpy
    import sys

    # Mock asyncio.run to prevent actual execution, just verify call
    mock_run = MagicMock()
    monkeypatch.setattr("asyncio.run", mock_run)

    with patch.object(sys, "argv", ["trace_recorder.py", "http://custom-url"]):
        # Clear from sys.modules to avoid RuntimeWarning when using runpy
        sys.modules.pop("eval_runner.trace_recorder", None)
        runpy.run_module("eval_runner.trace_recorder", run_name="__main__")

    mock_run.assert_called_once()
    # Close the coroutine to prevent RuntimeWarning: coroutine was never awaited
    coro = mock_run.call_args[0][0]
    coro.close()
