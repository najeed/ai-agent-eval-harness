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
        "metadata": {"id": "test-id", "name": "Test Scenario"},
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
        assert session.scenario == scenario
        assert session.fork_depth == 0
        assert session.max_turns >= 5

    @pytest.mark.asyncio
    async def test_execute_tasks_empty_workflow(self):
        with patch("eval_runner.events.EventEmitter.emit"):
            session = SessionManager("test_run", {"aes_version": 1.4, "workflow": {"nodes": []}})
            with pytest.raises(ValueError) as cm:
                await session.execute_tasks(1)
            assert "Unified Standard v1.4.0" in str(cm.value)

    @pytest.mark.asyncio
    async def test_execute_tasks_cycle_error(self):
        with patch("eval_runner.events.EventEmitter.emit"):
            scenario_cycle = {
                "workflow": {
                    "nodes": [{"id": "A"}, {"id": "B"}],
                    "edges": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
                }
            }
            session = SessionManager("test_run", scenario_cycle)
            with pytest.raises(ValueError) as cm:
                await session.execute_tasks(1)
            assert "cyclic dependencies" in str(cm.value)

    @pytest.mark.asyncio
    async def test_execute_tasks_happy_path(self, session):
        with patch(
            "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call_agent:
            with patch("eval_runner.tool_sandbox.ToolSandbox") as mock_sandbox_cls:
                with patch("eval_runner.events.EventEmitter.emit"):
                    with patch("eval_runner.plugins.manager.trigger"):
                        mock_sandbox = mock_sandbox_cls.return_value
                        mock_sandbox.state = {"val": 1}
                        mock_sandbox.teardown = AsyncMock()
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
            "eval_runner.engine.AgentAdapterRegistry.call_agent",
            side_effect=Exception("Connection Refused"),
        ):
            with patch("eval_runner.tool_sandbox.ToolSandbox") as mock_sandbox_cls:
                mock_sandbox = mock_sandbox_cls.return_value
                mock_sandbox.teardown = AsyncMock()
                with patch("eval_runner.events.EventEmitter.emit") as mock_emit:
                    results = await session.execute_tasks(1)
                    assert len(results) >= 1
                    error_emits = [
                        args[0] for args, kwargs in mock_emit.call_args_list if args[0] == "error"
                    ]
                    assert "error" in error_emits

    @pytest.mark.asyncio
    async def test_handle_tool_call_blocked(self, session):
        with patch.object(session.plugin_manager, "trigger_interceptor", return_value=False):
            with patch("eval_runner.events.EventEmitter.emit") as mock_emit:
                mock_ctx = MagicMock(spec=TurnContext)
                mock_sandbox = MagicMock()
                mock_sandbox.execute = AsyncMock(return_value={"status": "success"})
                mock_sandbox.state = {}
                history = []
                actions = {"used_tools": []}

                await session._handle_tool_call(
                    1, {"tool_name": "ls"}, mock_sandbox, history, actions, mock_ctx
                )

                assert len(history) == 0
                mock_sandbox.execute.assert_not_called()
                error_emits = [
                    kwargs["data"] if "data" in kwargs else args[1]
                    for args, kwargs in mock_emit.call_args_list
                    if args[0] == "error"
                ]
                assert any("blocked by plugin" in str(e) for e in error_emits)

    @pytest.mark.asyncio
    async def test_handle_tool_call_success(self, session):
        with patch("eval_runner.plugins.manager.trigger_interceptor", return_value=True):
            with patch("eval_runner.events.EventEmitter.emit"):
                with patch("eval_runner.plugins.manager.trigger"):
                    mock_ctx = MagicMock(spec=TurnContext)
                    mock_sandbox = MagicMock()
                    mock_sandbox.state = {"cwd": "/"}
                    mock_sandbox.execute = AsyncMock(return_value={"output": "ok"})
                    history = []
                    actions = {"used_tools": []}

                    await session._handle_tool_call(
                        1,
                        {"tool_name": "ls", "tool_params": {}},
                        mock_sandbox,
                        history,
                        actions,
                        mock_ctx,
                    )

                    assert len(history) == 1
                    assert history[0]["role"] == "environment"
                    assert history[0]["content"] == {"output": "ok"}
                    assert "ls" in actions["used_tools"]

    @pytest.mark.asyncio
    async def test_handle_multiple_tools(self, session):
        with patch.object(session.plugin_manager, "trigger_interceptor") as mock_interceptor:
            with patch("eval_runner.events.EventEmitter.emit"):
                mock_interceptor.side_effect = [True, False]
                mock_sandbox = MagicMock()
                mock_sandbox.state = {}
                mock_sandbox.execute = AsyncMock(return_value={"status": "success", "data": "res"})
                history = []
                actions = {"used_tools": []}

                await session._handle_multiple_tools(
                    1, {"tool_names": ["t1", "t2"]}, mock_sandbox, history, actions, MagicMock()
                )

                assert len(history) == 1
                content = history[0]["content"]
                assert len(content) == 2
                assert content[0]["status"] == "success"
                assert "blocked" in content[1]["status"]

    @pytest.mark.asyncio
    async def test_handle_hitl_ci(self, session):
        with patch("eval_runner.events.EventEmitter.emit"):
            with patch.dict(os.environ, {"CI": "true"}):
                res = await session._handle_hitl("task-1", "approve?")
                assert "Auto-approved" in res

    @pytest.mark.asyncio
    async def test_handle_hitl_tty(self, session):
        with patch("eval_runner.events.EventEmitter.emit"):
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="yes"):
                    res = await session._handle_hitl("task-1", "approve?")
                    assert res == "yes"

    @pytest.mark.asyncio
    async def test_handle_hitl_non_interactive(self, session):
        with patch("eval_runner.events.EventEmitter.emit"):
            with patch("sys.stdin.isatty", return_value=False):
                res = await session._handle_hitl("task-1", "approve?")
                assert "Simulation" in res

    @pytest.mark.asyncio
    async def test_calculate_metrics_state_hygiene(self, session):
        node = {
            "id": "node-1",
            "state_hygiene": {
                "rules": [
                    {"path": "git.branch", "expected": "main", "op": "eq"},
                    {"path": "db['active']", "expected": True, "op": "eq"},
                    {"path": "missing", "op": "not_exists"},
                    {"path": "db", "op": "exists"},
                    {"path": "tags", "expected": "v1.2", "op": "contains"},
                ]
            },
        }
        mock_sandbox = MagicMock()
        mock_sandbox.state = {
            "git": {"branch": "main"},
            "db": {"active": True},
            "tags": ["v1.1", "v1.2"],
        }

        results = await session._calculate_metrics(node, 1, 5, [], mock_sandbox, {"used_tools": []})

        hygiene = results["state_hygiene"]
        assert len(hygiene) == 5
        for h in hygiene:
            assert h["success"], f"Failed op {h['op']} for path {h['path']}"

    def test_sanitize_for_history(self, session):
        assert session._sanitize_for_history(1) == 1
        assert session._sanitize_for_history([1, {"a": 2}]) == [1, {"a": 2}]
        m = MagicMock()
        m.__str__.return_value = "Mocked"
        res = session._sanitize_for_history(m)
        assert isinstance(res, str)

    def test_fork_and_limits(self, session):
        import eval_runner.session as session_module

        s1 = session.fork([], {})
        assert s1.fork_depth == 1

        original_depth = session_module.MAX_FORK_DEPTH
        try:
            session_module.MAX_FORK_DEPTH = 1
            with pytest.raises(RuntimeError) as cm:
                s1.fork([], {})
            assert "Maximum depth" in str(cm.value)
        finally:
            session_module.MAX_FORK_DEPTH = original_depth

    @pytest.mark.asyncio
    async def test_get_last_env_message(self, session):
        assert session._get_last_env_message([]) == ""
        assert session._get_last_env_message([{"role": "agent"}]) == ""
        assert (
            session._get_last_env_message(
                [{"role": "environment", "content": {"message": "direct"}}]
            )
            == "direct"
        )
        assert (
            session._get_last_env_message([{"role": "environment", "content": ["list"]}])
            == 'Tools returned: ["list"]'
        )
        assert (
            session._get_last_env_message(
                [{"role": "environment", "content": {"message": "wrapped"}}]
            )
            == "wrapped"
        )

    def test_extract_agent_summary(self, session):
        assert session._extract_agent_summary([]) == ""
        assert (
            session._extract_agent_summary([{"role": "agent", "content": {"summary": "sum"}}])
            == "sum"
        )
        assert (
            session._extract_agent_summary([{"role": "agent", "content": {"content": "ccc"}}])
            == "ccc"
        )
        assert session._extract_agent_summary([{"role": "agent", "content": "plain"}]) == "plain"

    @pytest.mark.asyncio
    async def test_calculate_metrics_errors(self, session):
        with patch("eval_runner.metrics.MetricRegistry.get") as mock_get:
            mock_get.return_value = MagicMock(side_effect=Exception("Metric Boom"))
            node = {"id": "n1", "success_criteria": [{"metric": "m1"}]}
            results = await session._calculate_metrics(
                node, 1, 1, [], MagicMock(), {"used_tools": []}
            )
            assert len(results["metrics"]) == 0

    @pytest.mark.asyncio
    async def test_execute_tasks_loop_variants(self, session):
        with patch(
            "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call:
            with patch("eval_runner.events.EventEmitter.emit"):
                mock_call.side_effect = [
                    {"action": "final_answer", "content": "over"},
                    {"action": "error", "message": "bad"},
                ]
                res = await session.execute_tasks(1)
                assert len(res) == 2

    @pytest.mark.asyncio
    async def test_execute_tasks_protocol_defaults(self, session):
        with patch(
            "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call:
            with patch("eval_runner.events.EventEmitter.emit"):
                mock_call.return_value = {"action": "final_answer"}
                session.session_metadata = {"protocol": "local"}
                with patch.dict(os.environ, {"AGENT_LOCAL_CMD": "my-cmd"}):
                    await session.execute_tasks(1)
                    mock_call.assert_called()
                    assert mock_call.call_args[1]["endpoint"] == "my-cmd"


if __name__ == "__main__":
    unittest.main()
