import pytest
import asyncio
from eval_runner.engine import AgentAdapterRegistry, run_evaluation
from eval_runner.plugins import BaseEvalPlugin, manager
from eval_runner.events import EventEmitter, CoreEvents
from eval_runner.session import SessionManager

class MockDiscoveryPlugin(BaseEvalPlugin):
    def on_discover_adapters(self, registry):
        registry.register("mock_proto", self.mock_adapter)
    
    async def mock_adapter(self, payload, endpoint=None):
        return {"action": "final_answer", "content": "Mock discovery works!"}

@pytest.mark.asyncio
async def test_advanced_adapter_discovery():
    """Verify that plugins can dynamically register adapters."""
    plugin = MockDiscoveryPlugin()
    manager.plugins.append(plugin)
    
    try:
        # AgentAdapterRegistry._discovered should be reset for clean test
        AgentAdapterRegistry._discovered = False
        response = await AgentAdapterRegistry.call_agent({}, protocol="mock_proto", endpoint="dummy")
        assert response["content"] == "Mock discovery works!"
    finally:
        manager.plugins.remove(plugin)

@pytest.mark.asyncio
async def test_hitl_pause_resume(monkeypatch):
    """Verify HITL pause and resume logic in SessionManager."""
    scenario = {
        "scenario_id": "hitl_test",
        "tasks": [{"task_id": "t1", "description": "test task"}],
        "max_turns": 2
    }
    
    # Mock call_agent to return hitl_pause then final_answer
    call_counts = 0
    async def mock_call_agent(payload, protocol="http", endpoint=None):
        nonlocal call_counts
        call_counts += 1
        if call_counts == 1:
            return {"action": "hitl_pause"}
        return {"action": "final_answer", "content": "Done"}
    
    monkeypatch.setattr(AgentAdapterRegistry, "call_agent", mock_call_agent)
    
    events = []
    def event_listener(event):
        events.append(event.name)
    
    EventEmitter.subscribe(event_listener)
    
    session = SessionManager(scenario)
    results = await session.execute_tasks(1)
    
    assert CoreEvents.HITL_PAUSE in events
    assert CoreEvents.HITL_RESUME in events
    assert results[0]["turns_taken"] == 2

@pytest.mark.asyncio
async def test_trajectory_branching(monkeypatch):
    """Verify non-linear branching logic."""
    scenario = {
        "scenario_id": "branch_test",
        "tasks": [{"task_id": "t1", "description": "start"}],
        "max_turns": 2
    }
    
    async def mock_call_agent(payload, protocol="http", endpoint=None):
        return {
            "action": "branch",
            "branches": [{"name": "branch_a", "message": "hello from branch a"}]
        }
    
    monkeypatch.setattr(AgentAdapterRegistry, "call_agent", mock_call_agent)
    
    session = SessionManager(scenario)
    # This just verifies it doesn't crash and handles the action
    results = await session.execute_tasks(1)
    assert results is not None
    
    # Verify fork method exists and returns a session
    forked = session.fork([], {})
    assert isinstance(forked, SessionManager)
