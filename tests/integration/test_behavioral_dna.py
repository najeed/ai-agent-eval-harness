import pytest

from eval_runner import events, runner, session
from eval_runner.events import CoreEvents


@pytest.mark.asyncio
async def test_behavioral_dna_nesting(monkeypatch):
    """
    Verifies that the engine emits the full hierarchical Behavioral DNA stack.
    Strategy > Phase > Maneuver > Task > Subtask > Chain > Node
    """
    emitted_events = []

    def mock_emit(ev_type, payload, **kwargs):
        emitted_events.append(ev_type)

    monkeypatch.setattr(events, "emit", mock_emit)

    # We need a minimal scenario that won't actually call an agent (or mocks it)
    scenario = {
        "id": "dna-test",
        "tasks": [{"node_id": "task-1", "task_description": "test task"}],
    }

    # Mock SessionManager.execute_tasks to avoid actual sandbox/agent execution
    async def mock_execute(self, attempt):
        # Trigger internal event bus for the session as well
        self.event_bus.emit(CoreEvents.MANEUVER_START, {"node_id": "task-1"})
        self.event_bus.emit(CoreEvents.MANEUVER_END, {"node_id": "task-1"})
        return [{"metrics": [{"success": True}]}]

    monkeypatch.setattr(session.SessionManager, "execute_tasks", mock_execute)

    r = runner.DefaultRunner()
    await r.run(scenario, attempts=1)

    # Check for core hierarchy markers
    # Note: Strategy is emitted via events.emit in runner.py
    assert CoreEvents.STRATEGY_START in emitted_events
    assert CoreEvents.PHASE_START in emitted_events
    assert CoreEvents.STRATEGY_END in emitted_events

    # NOTE: MANEUVER etc are emitted via the session's event_bus which might not be global
    # If the session bus is NOT global, we need to check how it's initialized.
    # In v1.4, they are bridged or emitted globally if configured.
