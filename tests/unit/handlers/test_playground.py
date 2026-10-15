"""
Test module for the interactive playground.
"""

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


@pytest.mark.asyncio
async def test_run_playground_tool_calls_and_server_error(aiohttp_server, monkeypatch, capsys):
    """Test tool calls (single and multiple), server error (non-200), empty inputs, and quit."""
    from aiohttp import web

    async def handle_agent(request):
        data = await request.json()
        task = data.get("task_description")
        if task == "tool_single":
            return web.json_response(
                {
                    "summary": "Executed calculator",
                    "action": "call_tool",
                    "tool_name": "calc",
                    "tool_params": {"expr": "2+2"},
                    "tool_output": "4",
                }
            )
        elif task == "tool_multi":
            return web.json_response(
                {
                    "summary": "Multiple tools executed",
                    "action": "call_multiple_tools",
                    "tool_names": ["search", "summarize"],
                }
            )
        elif task == "server_err":
            return web.Response(status=500)
        return web.json_response({"summary": "Normal response"})

    app = web.Application()
    app.router.add_post("/execute_task", handle_agent)
    server = await aiohttp_server(app)
    agent_url = f"http://{server.host}:{server.port}/execute_task"

    inputs = ["tool_single", "tool_multi", "server_err", "quit"]

    def mock_input(_):
        if not inputs:
            return "quit"
        return inputs.pop(0)

    monkeypatch.setattr("builtins.input", mock_input)

    await run_playground(agent_url)

    captured = capsys.readouterr().out
    assert "Tool: calc" in captured
    assert "Tools: search, summarize" in captured
    assert "Error 500" in captured


@pytest.mark.asyncio
async def test_run_playground_empty_input_exits(monkeypatch, capsys):
    """Test empty input exits playground loop immediately."""
    agent_url = "http://localhost:5001/execute_task"
    monkeypatch.setattr("builtins.input", lambda _: "")

    await run_playground(agent_url)

    captured = capsys.readouterr().out
    assert "Playground" in captured


def test_playground_main_entrypoint(monkeypatch):
    """Test __main__ block execution when invoked as main module."""
    import runpy

    monkeypatch.setattr("builtins.input", lambda _: "exit")
    monkeypatch.setenv("AGENT_API_URL", "http://localhost:5001/execute_task")

    runpy.run_module("eval_runner.playground", run_name="__main__")
