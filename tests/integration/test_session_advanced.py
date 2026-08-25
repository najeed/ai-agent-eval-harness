import pytest

from eval_runner.engine import AgentAdapterRegistry
from eval_runner.events import CoreEvents
from eval_runner.plugins import BaseEvalPlugin, manager
from eval_runner.session import SessionManager


class MockDiscoveryPlugin(BaseEvalPlugin):
    def on_discover_adapters(self, registry):
        registry.register("mock_proto", self.mock_adapter)

    async def mock_adapter(self, payload, endpoint=None, **kwargs):
        return {"action": "final_answer", "content": "Mock discovery works!"}


@pytest.mark.asyncio
async def test_advanced_adapter_discovery():
    """Verify that plugins can dynamically register adapters."""
    plugin = MockDiscoveryPlugin()
    manager.plugins.append(plugin)

    try:
        # AgentAdapterRegistry._discovered should be reset for clean test
        AgentAdapterRegistry._discovered = False
        response = await AgentAdapterRegistry.call_agent("mock_proto", "dummy", "msg", [], None)
        assert response["content"] == "Mock discovery works!"
    finally:
        manager.plugins.remove(plugin)


@pytest.mark.asyncio
async def test_hitl_pause_resume(monkeypatch):
    """Verify HITL pause and resume logic in SessionManager."""
    scenario = {
        "aes_version": 1.4,
        "id": "hitl_test",
        "title": "HITL Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "hitl_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "test task",
                    "expected_outcome": {
                        "type": "typed_value",
                        "data_type": "string",
                        "value": "Done",
                    },
                    "required_tools": [],
                    "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
                }
            ],
            "edges": [],
        },
        "max_turns": 2,
    }

    # Registry Isolation: Ensure no stale state from other tests
    AgentAdapterRegistry.reset()
    # Throttle Control: Disable delays for test performance and reliability
    from eval_runner import config as eval_config

    monkeypatch.setattr(eval_config, "EVAL_TURN_THROTTLE", 0)
    # Mode pinning: this test exercises the full pause->RESUME handshake.
    # Ambient CI=true (GitHub Actions) would otherwise route _handle_hitl
    # into the fail-closed HITL_UNRESOLVED branch, which intentionally never
    # emits HITL_RESUME — that contract is covered by
    # test_hitl_ci_mode_fail_closed below.
    monkeypatch.delenv("CI", raising=False)

    # Mock call_agent to return hitl_pause then final_answer
    call_counts = 0
    received_turns = []

    async def mock_call_agent(protocol, endpoint, message, history, turn_ctx):
        nonlocal call_counts
        call_counts += 1
        received_turns.append(turn_ctx.turn_number)
        if call_counts == 1:
            return {"action": "hitl_pause"}
        return {"action": "final_answer", "content": "Done"}

    monkeypatch.setattr(AgentAdapterRegistry, "call_agent", mock_call_agent)

    events = []

    def event_listener(event):
        events.append(event.name)

    # Note: SessionManager uses an isolated bus; tests must subscribe to the instance
    session = SessionManager("hitl_test_run", scenario)
    session.event_bus.subscribe(event_listener)

    results = await session.execute_tasks(1)

    assert CoreEvents.HITL_PAUSE in events
    assert CoreEvents.HITL_RESUME in events
    assert call_counts == 2, f"Expected 2 calls to agent, got {call_counts}"
    assert received_turns == [1, 2], f"Expected turns [1, 2], got {received_turns}"
    assert results[0]["turns_taken"] == 2


@pytest.mark.asyncio
async def test_hitl_ci_mode_fail_closed(monkeypatch):
    """[P0-9] CI/automation contract: a hitl_pause under CI=true NEVER emits
    HITL_RESUME (no fabricated human decision). The run fails closed with an
    explicit HITL_UNRESOLVED triage after exactly one agent call."""
    scenario = {
        "aes_version": 1.4,
        "id": "hitl_ci_test",
        "title": "HITL CI Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "hitl_ci_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "test task",
                    "expected_outcome": {
                        "type": "typed_value",
                        "data_type": "string",
                        "value": "Done",
                    },
                    "required_tools": [],
                    "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
                }
            ],
            "edges": [],
        },
        "max_turns": 2,
    }

    AgentAdapterRegistry.reset()
    from eval_runner import config as eval_config

    monkeypatch.setattr(eval_config, "EVAL_TURN_THROTTLE", 0)
    # Force the exact environment GitHub Actions provides.
    monkeypatch.setenv("CI", "true")

    call_counts = 0

    async def mock_call_agent(protocol, endpoint, message, history, turn_ctx):
        nonlocal call_counts
        call_counts += 1
        return {"action": "hitl_pause"}

    monkeypatch.setattr(AgentAdapterRegistry, "call_agent", mock_call_agent)

    events = []

    def event_listener(event):
        events.append(event.name)

    session = SessionManager("hitl_ci_test_run", scenario)
    session.event_bus.subscribe(event_listener)

    results = await session.execute_tasks(1)

    # The pause is audited; the resume is never fabricated.
    assert CoreEvents.HITL_PAUSE in events
    assert CoreEvents.HITL_RESUME not in events, (
        "CI mode must not emit HITL_RESUME — no human decision was made"
    )
    # Fail-fast: the unresolved approval aborts the node after ONE agent call.
    assert call_counts == 1, f"Expected exactly 1 agent call, got {call_counts}"
    assert results[0]["triage_tag"] == "HITL_UNRESOLVED"
    assert "auto-approve" in results[0]["message"]


@pytest.mark.asyncio
async def test_trajectory_branching(monkeypatch):
    """Verify non-linear branching logic."""
    scenario = {
        "aes_version": 1.4,
        "id": "branch_test",
        "title": "Branch Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "branch_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "start",
                    "expected_outcome": {
                        "type": "typed_value",
                        "data_type": "string",
                        "value": "Done",
                    },
                    "required_tools": [],
                    "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
                }
            ],
            "edges": [],
        },
        "max_turns": 2,
    }

    async def mock_call_agent(protocol, endpoint, message, history, turn_ctx):
        return {
            "action": "branch",
            "branches": [{"name": "branch_a", "message": "hello from branch a"}],
        }

    monkeypatch.setattr(AgentAdapterRegistry, "call_agent", mock_call_agent)

    session = SessionManager("branch_test_run", scenario)
    # This just verifies it doesn't crash and handles the action
    results = await session.execute_tasks(1)
    assert results is not None

    # Verify fork method exists and returns a session
    forked = session.fork([], {})
    assert type(forked).__name__ == "SessionManager"
