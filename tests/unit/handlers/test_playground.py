"""
Test module for the interactive playground.
"""

import sys

import pytest

from eval_runner.playground import run_playground

@pytest.mark.asyncio
async def test_run_playground_flow(monkeypatch, adapter_stub, capsys):
    """Test the interactive playground loop with a real local server stub."""
    server = adapter_stub
    agent_url = f"http://{server.host}:{server.port}/execute_task"

    inputs = ["Hello agent", "exit"]

    def mock_input(_):
        if not inputs:
            return "exit"
        return inputs.pop(0)

    monkeypatch.setattr("builtins.input", mock_input)

    await run_playground(agent_url)

    captured = capsys.readouterr().out
    assert "USER: Hello agent" in captured
    assert "AGENT: This is a joke" in captured


@pytest.mark.asyncio
async def test_run_playground_error(monkeypatch, capsys):
    """Test error handling in playground with real connection failure."""
    agent_url = "http://localhost:65534/execute_task"

    inputs = ["Crash", "exit"]

    def mock_input(_):
        if not inputs:
            return "exit"
        return inputs.pop(0)

    monkeypatch.setattr("builtins.input", mock_input)

    await run_playground(agent_url)

    captured = capsys.readouterr().out
    assert "Connection Error" in captured
