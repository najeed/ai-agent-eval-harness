import asyncio
import pytest
from eval_runner.session import SessionManager
from eval_runner.events import CoreEvents, EventEmitter

@pytest.fixture
def minimal_scenario():
    return {
        "scenario_id": "test_isolation",
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "test"}],
            "edges": []
        }
    }

@pytest.mark.asyncio
async def test_event_bus_isolation(minimal_scenario):
    """Verify that events emitted in one session do not bleed into another."""
    session_a = SessionManager("run-a", minimal_scenario)
    session_b = SessionManager("run-b", minimal_scenario)
    
    received_a = []
    received_b = []
    
    session_a.event_bus.subscribe(lambda e: received_a.append(e))
    session_b.event_bus.subscribe(lambda e: received_b.append(e))
    
    # Emit on A
    session_a.event_bus.emit("event_a", {"id": "a"})
    # Emit on B
    session_b.event_bus.emit("event_b", {"id": "b"})
    
    # Wait a bit for async dispatch if any (though currently synchronous)
    await asyncio.sleep(0.1)
    
    assert any(e.name == "event_a" for e in received_a)
    assert not any(e.name == "event_b" for e in received_a)
    
    assert any(e.name == "event_b" for e in received_b)
    assert not any(e.name == "event_a" for e in received_b)

@pytest.mark.asyncio
async def test_global_vs_session_leakage(minimal_scenario):
    """Verify that global listeners do not receive session-specific events by default."""
    session = SessionManager("run-scoped", minimal_scenario)
    
    global_received = []
    from eval_runner.events import subscribe
    subscribe(lambda e: global_received.append(e))
    
    session.event_bus.emit("private_event", {})
    
    await asyncio.sleep(0.1)
    
    # Global listener should not see private session events
    assert not any(e.name == "private_event" for e in global_received)

@pytest.mark.asyncio
async def test_plugin_scoped_listeners(minimal_scenario):
    """Verify that plugins are correctly scoped to their session buses."""
    from eval_runner.plugins import BaseEvalPlugin
    
    class TestPlugin(BaseEvalPlugin):
        def __init__(self):
            self.events = []
        def on_run_start(self, run_id, **kwargs):
            self.events.append(run_id)
            
    plugin_a = TestPlugin()
    plugin_b = TestPlugin()
    
    session_a = SessionManager("run-a", minimal_scenario)
    session_b = SessionManager("run-b", minimal_scenario)
    
    # Register plugins to their respective sessions
    session_a.plugin_manager.plugins.append(plugin_a)
    session_b.plugin_manager.plugins.append(plugin_b)
    
    # Trigger events via session buses
    session_a.event_bus.emit(CoreEvents.RUN_START, {"run_id": "run-a"})
    session_b.event_bus.emit(CoreEvents.RUN_START, {"run_id": "run-b"})
    
    await asyncio.sleep(0.1)
    
    assert "run-a" in plugin_a.events
    assert "run-b" not in plugin_a.events
    
    assert "run-b" in plugin_b.events
    assert "run-a" not in plugin_b.events
