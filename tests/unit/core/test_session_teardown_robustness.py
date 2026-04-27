from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.session import SessionManager


@pytest.mark.asyncio
async def test_teardown_on_cycle_error():
    """
    Verify that sandbox.teardown is called even if a CycleError occurs.
    """
    scenario_cycle = {
        "id": "cycle-test",
        "workflow": {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
        },
    }

    session = SessionManager("run-cycle", scenario_cycle)

    with patch("eval_runner.session.ToolSandbox") as mock_sandbox_cls:
        mock_sandbox = mock_sandbox_cls.return_value
        mock_sandbox.setup = AsyncMock()
        mock_sandbox.teardown = AsyncMock()

        # In the hardened version, execute_tasks catches the ValueError and returns failure results
        results = await session.execute_tasks(1)

        assert len(results) == 1
        assert results[0]["status"] == "failure"
        assert "Cyclic dependencies" in results[0]["message"]
        # CRITICAL: Teardown must be called
        mock_sandbox.teardown.assert_called_once()


@pytest.mark.asyncio
async def test_teardown_on_setup_failure():
    """
    Verify that teardown is attempted even if setup fails partway.
    """
    scenario = {"id": "test", "workflow": {"nodes": [{"id": "n1"}]}}
    session = SessionManager("run-fail", scenario)

    with patch("eval_runner.session.ToolSandbox") as mock_sandbox_cls:
        mock_sandbox = mock_sandbox_cls.return_value
        mock_sandbox.setup = AsyncMock(side_effect=RuntimeError("Setup Crash"))
        mock_sandbox.teardown = AsyncMock()

        results = await session.execute_tasks(1)

        assert len(results) == 1
        assert results[0]["status"] == "failure"
        assert "Setup Crash" in results[0]["message"]
        # Teardown should still be called to clean up any partial state
        mock_sandbox.teardown.assert_called_once()
