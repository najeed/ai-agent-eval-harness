"""
tests/test_architecture.py

Verifies the Zero-Touch Core architectural improvements.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from eval_runner.events import EventEmitter, CoreEvents
from eval_runner.runner import DefaultRunner
from eval_runner.plugins import BaseEvalPlugin, manager
from eval_runner.context import TurnContext

@pytest.mark.asyncio
async def test_event_emission():
    # Setup subscriber
    events_received = []
    def subscriber(event):
        events_received.append(event.name)
    
    EventEmitter.subscribe(subscriber)
    EventEmitter.emit(CoreEvents.RUN_START, {"run_id": "test"})
    
    assert CoreEvents.RUN_START in events_received

@pytest.mark.asyncio
async def test_plugin_interception():
    # Setup blocking plugin
    class BlockingPlugin(BaseEvalPlugin):
        def on_tool_request(self, context, tool_name, args):
            if tool_name == "forbidden_tool":
                return False
            return True

    manager.plugins.append(BlockingPlugin())
    
    # Simulate interceptor check
    ctx = MagicMock(spec=TurnContext)
    allowed = manager.trigger_interceptor("on_tool_request", ctx, "forbidden_tool", {})
    assert allowed is False
    
    allowed_safe = manager.trigger_interceptor("on_tool_request", ctx, "safe_tool", {})
    assert allowed_safe is True
    
    # Cleanup
    manager.plugins = [p for p in manager.plugins if not isinstance(p, BlockingPlugin)]

@pytest.mark.asyncio
async def test_runner_orchestration(monkeypatch):
    # Mock dependencies to avoid real network/IO
    from eval_runner.engine import AgentAdapterRegistry
    monkeypatch.setattr(AgentAdapterRegistry, "call_agent", AsyncMock(return_value={"action": "final_answer"}))
    
    scenario = {
        "scenario_id": "test_scenario",
        "tasks": [{"task_id": "t1", "description": "test task"}]
    }
    
    runner = DefaultRunner()
    results = await runner.run(scenario, attempts=2)
    
    assert len(results) == 2
    assert results[0][0]["task_id"] == "t1"
