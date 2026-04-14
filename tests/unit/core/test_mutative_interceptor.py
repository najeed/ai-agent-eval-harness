# tests/unit/core/test_mutative_interceptor.py

from unittest.mock import AsyncMock, MagicMock

import pytest

from eval_runner.plugins import BaseEvalPlugin, PluginManager
from eval_runner.session import SessionManager


class MutativeRedirectionPlugin(BaseEvalPlugin):
    """Mocks a plugin that redirects 'old_tool' to 'database_query'."""

    def on_tool_request(self, context, tool_name, arguments):
        if tool_name == "old_tool":
            return {"tool_name": "database_query", "arguments": {"query": "SELECT * FROM users"}}
        return True


class ShortCircuitPlugin(BaseEvalPlugin):
    """Mocks a plugin that short-circuits a specific call."""

    def on_tool_request(self, context, tool_name, arguments):
        if tool_name == "identity_check":
            return {"short_circuit_result": {"status": "success", "identity": "verified_by_plugin"}}
        return True


@pytest.mark.asyncio
async def test_mutative_tool_redirection():
    # Setup
    pm = PluginManager()
    pm.plugins = [MutativeRedirectionPlugin()]

    # Mock Sandbox
    sandbox = AsyncMock()
    sandbox.state = {}
    sandbox.execute = AsyncMock(return_value={"status": "success", "rows": []})

    session = SessionManager(run_id="run_1", scenario={"id": "test"})
    session.plugin_manager = pm

    agent_response = {"action": "call_tool", "tool_name": "old_tool", "tool_params": {}}
    history = []
    actions = {"used_tools": []}
    turn_ctx = MagicMock()

    # Execute
    await session._handle_tool_call(1, agent_response, sandbox, history, actions, turn_ctx)

    # Assertions
    # 1. The sandbox should have been called with the NEW tool name and NEW params
    sandbox.execute.assert_called_once_with("database_query", {"query": "SELECT * FROM users"})
    # 2. Used tools should track the NEW name
    assert "database_query" in actions["used_tools"]


@pytest.mark.asyncio
async def test_tool_short_circuit():
    # Setup
    pm = PluginManager()
    pm.plugins = [ShortCircuitPlugin()]

    # Mock Sandbox
    sandbox = AsyncMock()
    sandbox.execute = AsyncMock()  # Should NOT be called

    session = SessionManager(run_id="run_1", scenario={"id": "test"})
    session.plugin_manager = pm

    agent_response = {"action": "call_tool", "tool_name": "identity_check", "tool_params": {}}
    history = []
    actions = {"used_tools": []}
    turn_ctx = MagicMock()

    # Execute
    await session._handle_tool_call(1, agent_response, sandbox, history, actions, turn_ctx)

    # Assertions
    # 1. Sandbox should NOT have been called
    sandbox.execute.assert_not_called()
    # 2. History should contain the short-circuited result
    assert history[-1]["content"]["identity"] == "verified_by_plugin"
