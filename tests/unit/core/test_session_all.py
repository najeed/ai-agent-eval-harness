import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.context import TurnContext

# SUT
from eval_runner.session import SessionManager


@pytest.fixture
def scenario():
    return {
        "aes_version": 1.4,
        "id": "test-scenario-v1",
        "metadata": {"id": "test-scenario-v1", "name": "Test Scenario"},
        "workflow": {
            "nodes": [
                {"id": "task-1", "task_description": "First task"},
                {"id": "task-2", "task_description": "Second task"},
            ],
            "edges": [{"from": "task-1", "to": "task-2"}],
        },
    }


@pytest.fixture
def metadata():
    return {"protocol": "http", "agent": "http://localhost:5000"}


@pytest.fixture
def session(scenario, metadata):
    return SessionManager("test_run", scenario, metadata=metadata)


class TestSession:
    def test_init(self, session, scenario):
        # We verify core keys instead of full dict equality as SessionManager adds resolved metadata
        assert session.scenario["id"] == scenario["id"]
        assert session.identifier == scenario["id"]
        assert session.session_metadata["protocol"] == "http"
        assert "agent" in session.session_metadata
        assert session.fork_depth == 0
        assert session.max_turns >= 5

    @pytest.mark.asyncio
    async def test_execute_tasks_empty_workflow(self):
        with patch("eval_runner.events.EventEmitter.emit"):
            session = SessionManager(
                "test_run", {"aes_version": 1.4, "id": "empty-v1", "workflow": {"nodes": []}}
            )
            results = await session.execute_tasks(1)
            assert len(results) == 1
            assert results[0]["status"] == "failure"
            assert "Industrial Fail-Fast (v1.4.0)" in results[0]["message"]

    @pytest.mark.asyncio
    async def test_execute_tasks_cycle_error(self):
        with patch("eval_runner.events.EventEmitter.emit"):
            scenario_cycle = {
                "workflow": {
                    "nodes": [{"id": "A"}, {"id": "B"}],
                    "edges": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
                }
            }
            session = SessionManager("test_run", {**scenario_cycle, "id": "cycle-v1"})
            results = await session.execute_tasks(1)
            assert len(results) == 1
            assert results[0]["status"] == "failure"
            assert "Cyclic dependencies detected" in results[0]["message"]

    @pytest.mark.asyncio
    async def test_execute_tasks_happy_path(self, session):
        with patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call_agent:
            with patch("eval_runner.session.ToolSandbox") as mock_sandbox_cls:
                with patch("eval_runner.events.EventEmitter.emit"):
                    with patch("eval_runner.plugins.manager.trigger"):
                        mock_sandbox = mock_sandbox_cls.return_value
                        mock_sandbox.state = {"val": 1}
                        mock_sandbox.setup = AsyncMock()
                        mock_sandbox.teardown = AsyncMock()
                        mock_sandbox.get_full_state = AsyncMock(
                            return_value={"world": mock_sandbox.state}
                        )
                        mock_call_agent.return_value = {"action": "final_answer", "content": "Done"}

                        results = await session.execute_tasks(attempt_number=1)

                        assert len(results) == 2
                        assert results[0]["task_id"] == "task-1"
                        assert results[1]["task_id"] == "task-2"
                        assert mock_call_agent.call_count == 2
                        mock_sandbox.setup.assert_called()
                        mock_sandbox.teardown.assert_called()

    @pytest.mark.asyncio
    async def test_execute_tasks_agent_error(self, session):
        with patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call_agent:
            with patch("eval_runner.session.ToolSandbox") as mock_sandbox_cls:
                with patch("eval_runner.events.EventEmitter.emit"):
                    mock_sandbox = mock_sandbox_cls.return_value
                    mock_sandbox.setup = AsyncMock()
                    mock_sandbox.teardown = AsyncMock()
                    mock_sandbox.get_full_state = AsyncMock(return_value={})
                    mock_call_agent.side_effect = Exception("Agent Crash")

                    results = await session.execute_tasks(1)
                    assert len(results) == 1
                    assert results[0]["status"] == "failure"
                    assert "Agent Crash" in results[0]["message"]

    @pytest.mark.asyncio
    async def test_execute_node_turn_loop(self, session):
        # verify turns are counted
        mock_sandbox = MagicMock()
        mock_sandbox.get_full_state = AsyncMock(return_value={})
        history = []
        actions = {"used_tools": []}
        node = {"id": "n1", "task_description": "t1"}

        with patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call:
            # First turn: call tool, second turn: final answer
            mock_call.side_effect = [
                {"action": "call_tool", "tool_name": "t1"},
                {"action": "final_answer"},
            ]

            with patch.object(session, "_handle_tool_call", new_callable=AsyncMock):
                res = await session._execute_node(node, 1, 0, mock_sandbox, history, actions)
                assert res["turns_taken"] == 2
                assert mock_call.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_tool_call(self, session):
        mock_sandbox = MagicMock()
        mock_sandbox.execute = AsyncMock(return_value="tool output")
        mock_sandbox.get_full_state = AsyncMock(return_value={})
        mock_sandbox.state = {}
        history = []
        actions = {"used_tools": []}
        agent_resp = {"tool_name": "my_tool", "tool_params": {"p1": "v1"}}
        turn_ctx = TurnContext("n1", 1, "msg", [], None)

        await session._handle_tool_call(1, agent_resp, mock_sandbox, history, actions, turn_ctx)

        mock_sandbox.execute.assert_called_with("my_tool", {"p1": "v1"})
        assert actions["used_tools"] == ["my_tool"]
        assert any("tool output" in str(h) for h in history)

    @pytest.mark.asyncio
    async def test_handle_hitl(self, session):
        with (
            patch("builtins.input", return_value="human feedback"),
            patch("sys.stdin.isatty", return_value=True),
            patch.dict(os.environ, {"CI": "false"}),
        ):
            resp = {"action": "hitl_pause", "prompt": "Need help"}
            turn_ctx = TurnContext("n1", 1, "msg", [], None)
            res = await session._handle_hitl(1, resp, [], {}, turn_ctx)
            assert res == "human feedback"

    @pytest.mark.asyncio
    async def test_verify_state_parity(self, session):
        node = {
            "expected_outcome": [
                {"target": "state", "property": "$.user.name", "expected": "Najeed"}
            ]
        }
        mock_sandbox = MagicMock()
        mock_sandbox.get_full_state = AsyncMock(return_value={"user": {"name": "Najeed"}})

        assert await session._verify_state_parity(node, mock_sandbox, []) is True

        mock_sandbox.get_full_state.return_value = {"user": {"name": "Wrong"}}
        assert await session._verify_state_parity(node, mock_sandbox, []) is False

    @pytest.mark.asyncio
    async def test_calculate_metrics(self, session):
        node = {"success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}]}
        mock_sandbox = MagicMock()
        mock_sandbox.get_full_state = AsyncMock(return_value={})
        actions = {"used_tools": []}

        res = await session._calculate_metrics(node, 1, 1, [], mock_sandbox, actions)
        assert "metrics" in res
        assert len(res["metrics"]) >= 1

    @pytest.mark.asyncio
    async def test_execute_tasks_protocol_defaults(self, scenario):
        with patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call:
            with patch("eval_runner.events.EventEmitter.emit"):
                mock_call.return_value = {"action": "final_answer"}
                # [Fix] Create a fresh session to trigger protocol resolution in __init__
                with patch.dict(os.environ, {"AGENT_LOCAL_CMD": "my-cmd"}):
                    session = SessionManager(
                        "test_run", scenario, metadata={"protocol": "local", "agent": None}
                    )
                    await session.execute_tasks(1)
                    mock_call.assert_called()
                    # Positional arguments: (protocol, endpoint, message, history, turn_ctx)
                    # endpoint is index 1
                    assert mock_call.call_args[0][1] == "my-cmd"

    @pytest.mark.asyncio
    async def test_execute_node_unknown_action_failure(self, session):
        # verify unknown action causes failure
        mock_sandbox = MagicMock()
        mock_sandbox.get_full_state = AsyncMock(return_value={})
        history = []
        actions = {"used_tools": []}
        node = {"id": "n1", "task_description": "t1"}

        with patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call:
            mock_call.return_value = {"action": "invalid_action_name"}

            res = await session._execute_node(node, 1, 0, mock_sandbox, history, actions)
            assert res["status"] == "failure"
            assert "Unknown Agent Action" in res["message"]


if __name__ == "__main__":
    unittest.main()
