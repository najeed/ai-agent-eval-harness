import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import json
import asyncio
import os
import sys
import copy

# SUT
from eval_runner.session import SessionManager
from eval_runner.context import TurnContext

class TestSession(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.scenario = {
            "metadata": {"id": "test-id", "name": "Test Scenario"},
            "workflow": {
                "nodes": [
                    {"id": "task-1", "task_description": "First task"},
                    {"id": "task-2", "task_description": "Second task"}
                ],
                "edges": [
                    {"from": "task-1", "to": "task-2"}
                ]
            }
        }
        self.metadata = {"protocol": "http", "agent": "http://localhost:5000"}
        self.session = SessionManager(self.scenario, self.metadata)

    def test_init(self):
        self.assertEqual(self.session.scenario, self.scenario)
        self.assertEqual(self.session.fork_depth, 0)
        # Default MAX_TURNS fallback (EVAL_MAX_TURNS is 5 by default)
        self.assertTrue(self.session.max_turns >= 5)

    @patch("eval_runner.events.EventEmitter.emit")
    async def test_execute_tasks_empty_workflow(self, mock_emit):
        session = SessionManager({"workflow": {"nodes": []}})
        with self.assertRaises(ValueError) as cm:
            await session.execute_tasks(1)
        self.assertIn("missing required 'workflow' block", str(cm.exception))

    @patch("eval_runner.events.EventEmitter.emit")
    async def test_execute_tasks_cycle_error(self, mock_emit):
        scenario_cycle = {
            "workflow": {
                "nodes": [{"id": "A"}, {"id": "B"}],
                "edges": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}]
            }
        }
        session = SessionManager(scenario_cycle)
        with self.assertRaises(ValueError) as cm:
            await session.execute_tasks(1)
        self.assertIn("cyclic dependencies", str(cm.exception))

    @patch("eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock)
    @patch("eval_runner.tool_sandbox.ToolSandbox")
    @patch("eval_runner.events.EventEmitter.emit")
    @patch("eval_runner.plugins.manager.trigger")
    async def test_execute_tasks_happy_path(self, mock_trigger, mock_emit, mock_sandbox_cls, mock_call_agent):
        mock_sandbox = mock_sandbox_cls.return_value
        mock_sandbox.state = {"val": 1}
        
        # Agent finishes in 1 turn for each task
        mock_call_agent.return_value = {"action": "final_answer", "content": "Done"}
        
        results = await self.session.execute_tasks(attempt_number=1)
        
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["task_id"], "task-1")
        self.assertEqual(results[1]["task_id"], "task-2")
        self.assertEqual(mock_call_agent.call_count, 2)
        mock_sandbox.setup.assert_called()
        mock_sandbox.teardown.assert_called()

    @patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=Exception("Connection Refused"))
    @patch("eval_runner.tool_sandbox.ToolSandbox")
    @patch("eval_runner.events.EventEmitter.emit")
    async def test_execute_tasks_agent_error(self, mock_emit, mock_sandbox_cls, mock_call_agent):
        # Should break loop and emit error
        results = await self.session.execute_tasks(1)
        # One result should be there (empty or partial from the failed task)
        self.assertTrue(len(results) >= 1)
        # Check for ERROR emit
        error_emits = [args[0] for args, kwargs in mock_emit.call_args_list if args[0] == "error"]
        self.assertIn("error", error_emits)

    @patch("eval_runner.plugins.manager.trigger_interceptor", return_value=False)
    @patch("eval_runner.events.EventEmitter.emit")
    async def test_handle_tool_call_blocked(self, mock_emit, mock_interceptor):
        mock_ctx = MagicMock(spec=TurnContext)
        mock_sandbox = MagicMock()
        history = []
        actions = {"used_tools": []}
        
        await self.session._handle_tool_call(1, {"tool_name": "ls"}, mock_sandbox, history, actions, mock_ctx)
        
        self.assertEqual(len(history), 0)
        mock_sandbox.execute.assert_not_called()
        # Verify ERROR event
        error_emits = [kwargs["data"] if "data" in kwargs else args[1] for args, kwargs in mock_emit.call_args_list if args[0] == "error"]
        self.assertTrue(any("blocked by plugin" in str(e) for e in error_emits))

    @patch("eval_runner.plugins.manager.trigger_interceptor", return_value=True)
    @patch("eval_runner.events.EventEmitter.emit")
    @patch("eval_runner.plugins.manager.trigger")
    async def test_handle_tool_call_success(self, mock_trigger, mock_emit, mock_interceptor):
        mock_ctx = MagicMock(spec=TurnContext)
        mock_sandbox = MagicMock()
        mock_sandbox.state = {"cwd": "/"}
        mock_sandbox.execute.return_value = {"output": "ok"}
        history = []
        actions = {"used_tools": []}
        
        await self.session._handle_tool_call(1, {"tool_name": "ls", "tool_params": {}}, mock_sandbox, history, actions, mock_ctx)
        
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], "environment")
        self.assertEqual(history[0]["content"], {"output": "ok"})
        self.assertIn("ls", actions["used_tools"])
        mock_trigger.assert_called_with("on_tool_result", mock_ctx, "ls", {"output": "ok"})

    @patch("eval_runner.plugins.manager.trigger_interceptor")
    @patch("eval_runner.events.EventEmitter.emit")
    async def test_handle_multiple_tools(self, mock_emit, mock_interceptor):
        # Block one, allow one
        mock_interceptor.side_effect = [True, False]
        mock_sandbox = MagicMock()
        mock_sandbox.state = {}
        mock_sandbox.execute.return_value = "res"
        history = []
        actions = {"used_tools": []}
        
        await self.session._handle_multiple_tools(1, {"tool_names": ["t1", "t2"]}, mock_sandbox, history, actions, MagicMock())
        
        self.assertEqual(len(history), 1)
        # Content should have both results
        content = history[0]["content"]
        self.assertEqual(len(content), 2)
        self.assertEqual(content[0], "res")
        self.assertIn("blocked", content[1]["status"])

    @patch("eval_runner.events.EventEmitter.emit")
    async def test_handle_hitl_ci(self, mock_emit):
        with patch.dict(os.environ, {"CI": "true"}):
            res = await self.session._handle_hitl("task-1", "approve?")
            self.assertIn("Auto-approved", res)

    @patch("eval_runner.events.EventEmitter.emit")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="yes")
    async def test_handle_hitl_tty(self, mock_input, mock_isatty, mock_emit):
        res = await self.session._handle_hitl("task-1", "approve?")
        self.assertEqual(res, "yes")

    @patch("eval_runner.events.EventEmitter.emit")
    @patch("sys.stdin.isatty", return_value=False)
    async def test_handle_hitl_non_interactive(self, mock_isatty, mock_emit):
        res = await self.session._handle_hitl("task-1", "approve?")
        self.assertIn("Simulation", res)

    async def test_calculate_metrics_state_hygiene(self):
        # Line 320-360: State Hygiene
        node = {
            "id": "node-1",
            "state_hygiene": {
                "rules": [
                    {"path": "git.branch", "expected": "main", "op": "eq"},
                    {"path": "db['active']", "expected": True, "op": "eq"},
                    {"path": "missing", "op": "not_exists"},
                    {"path": "db", "op": "exists"},
                    {"path": "tags", "expected": "v1.2", "op": "contains"}
                ]
            }
        }
        mock_sandbox = MagicMock()
        mock_sandbox.state = {
            "git": {"branch": "main"},
            "db": {"active": True},
            "tags": ["v1.1", "v1.2"]
        }
        
        results = await self.session._calculate_metrics(node, 1, 5, [], mock_sandbox, {"used_tools": []})
        
        hygiene = results["state_hygiene"]
        self.assertEqual(len(hygiene), 5)
        for h in hygiene:
            self.assertTrue(h["success"], f"Failed op {h['op']} for path {h['path']}")

    def test_sanitize_for_history(self):
        # Line 415-433
        self.assertEqual(self.session._sanitize_for_history(1), 1)
        self.assertEqual(self.session._sanitize_for_history([1, {"a": 2}]), [1, {"a": 2}])
        # Test mock coercion
        m = MagicMock()
        m.__str__.return_value = "Mocked"
        # Since it's not a standard type and encoder might fail, it falls back to str()
        res = self.session._sanitize_for_history(m)
        self.assertIsInstance(res, str)

    def test_fork_and_limits(self):
        # Start at 0
        s1 = self.session.fork([], {})
        self.assertEqual(s1.fork_depth, 1)
        
        # Test depth limit (Line 439-440)
        with patch("eval_runner.session.MAX_FORK_DEPTH", 1):
             with self.assertRaises(RuntimeError) as cm:
                 s1.fork([], {})
             self.assertIn("Maximum depth", str(cm.exception))

    async def test_get_last_env_message(self):
        # Line 300-308
        self.assertEqual(self.session._get_last_env_message([]), "")
        self.assertEqual(self.session._get_last_env_message([{"role": "agent"}]), "")
        # Standard env roles should use dicts or lists
        self.assertEqual(self.session._get_last_env_message([{"role": "environment", "content": {"message": "direct"}}]), "direct")
        self.assertEqual(self.session._get_last_env_message([{"role": "environment", "content": ["list"]}]), 'Tools returned: ["list"]')
        self.assertEqual(self.session._get_last_env_message([{"role": "environment", "content": {"message": "wrapped"}}]), "wrapped")

    def test_extract_agent_summary(self):
        # Line 406-413
        self.assertEqual(self.session._extract_agent_summary([]), "")
        self.assertEqual(self.session._extract_agent_summary([{"role": "agent", "content": {"summary": "sum"}}]), "sum")
        self.assertEqual(self.session._extract_agent_summary([{"role": "agent", "content": {"content": "ccc"}}]), "ccc")
        self.assertEqual(self.session._extract_agent_summary([{"role": "agent", "content": "plain"}]), "plain")

    @patch("eval_runner.metrics.MetricRegistry.get")
    async def test_calculate_metrics_errors(self, mock_get):
        # Line 388-401 (Metric Error branch)
        mock_get.return_value = MagicMock(side_effect=Exception("Metric Boom"))
        node = {"id": "n1", "success_criteria": [{"metric": "m1"}]}
        results = await self.session._calculate_metrics(node, 1, 1, [], MagicMock(), {"used_tools": []})
        self.assertEqual(len(results["metrics"]), 0) # Should be caught and logged

    @patch("eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock)
    @patch("eval_runner.events.EventEmitter.emit")
    async def test_execute_tasks_loop_variants(self, mock_emit, mock_call):
        # Test line 177: final_answer / error break
        mock_call.side_effect = [
            {"action": "final_answer", "content": "over"},
            {"action": "error", "message": "bad"}
        ]
        res = await self.session.execute_tasks(1)
        self.assertEqual(len(res), 2)
        
    @patch("eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock)
    @patch("eval_runner.events.EventEmitter.emit")
    async def test_execute_tasks_protocol_defaults(self, mock_emit, mock_call):
        # Line 129-133
        mock_call.return_value = {"action": "final_answer"}
        self.session.session_metadata = {"protocol": "local"}
        with patch.dict(os.environ, {"AGENT_LOCAL_CMD": "my-cmd"}):
             await self.session.execute_tasks(1)
             mock_call.assert_called()
             self.assertEqual(mock_call.call_args[1]["endpoint"], "my-cmd")

if __name__ == '__main__':
    # Allow running both via unittest and our custom executor if needed,
    # but we use a specialized async wrapper in the file for standalone execution.
    unittest.main()
