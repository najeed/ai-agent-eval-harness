import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from eval_runner.playground import run_playground


@pytest.mark.asyncio
async def test_run_playground_flow(monkeypatch):
    """Test the interactive playground loop."""
    agent_url = "http://localhost:5001/execute_task"

    # Mock 'input' to return a task then 'exit'
    inputs = ["Hello agent", "exit"]
    input_mock = MagicMock(side_effect=inputs)

    # Mock aiohttp ClientSession and response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value={
            "summary": "Hello user!",
            "action": "call_tool",
            "tool_name": "search",
            "tool_params": {"query": "test"},
            "tool_output": "test results",
        }
    )
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    # Capture prints to verify formatting
    with patch("builtins.input", input_mock), patch("aiohttp.ClientSession", return_value=mock_session), patch(
        "builtins.print"
    ) as mock_print:

        await run_playground(agent_url)

        # Verify prints
        mock_print.assert_any_call("🚀 USER: Hello agent")
        mock_print.assert_any_call("🤖 AGENT: Hello user!")
        mock_print.assert_any_call("   🛠 Tool: search ({'query': 'test'})")
        mock_print.assert_any_call("   📦 Output: test results")


@pytest.mark.asyncio
async def test_run_playground_error(monkeypatch):
    """Test error handling in playground."""
    agent_url = "http://localhost:5001/execute_task"

    inputs = ["Crash", "exit"]
    input_mock = MagicMock(side_effect=inputs)

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=Exception("Server Down"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("builtins.input", input_mock), patch("aiohttp.ClientSession", return_value=mock_session), patch(
        "builtins.print"
    ) as mock_print:

        await run_playground(agent_url)

        mock_print.assert_any_call("❌ Connection Error: Server Down")
