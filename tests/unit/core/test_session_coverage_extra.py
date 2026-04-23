from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import eval_runner.engine
from eval_runner import config
from eval_runner.session import SessionManager


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "identities")
    (tmp_path / "runs").mkdir()
    (tmp_path / "identities").mkdir()
    return tmp_path


@pytest.mark.asyncio
async def test_session_init_routing_discovery(mock_config):
    # Covers lines 162-195 (Capability Discovery)
    scenario = {"id": "test_routing", "capabilities": ["high_performance_compute"], "metadata": {}}

    # RoutingRegistry is imported inside __init__, so we patch the source module
    with patch("eval_runner.routing.RoutingRegistry.resolve") as mock_resolve:
        mock_resolve.return_value = {
            "protocol": "socket",
            "endpoint": "localhost:9999",
            "metadata": {"mapping_overrides": {"a": "b"}, "extra": "data"},
        }
        session = SessionManager("run_id", scenario)

        assert session.session_metadata["protocol"] == "socket"
        assert session.session_metadata["agent"] == "localhost:9999"
        assert session.session_metadata["extra"] == "data"
        assert session.metadata["protocol"] == "socket"


@pytest.mark.asyncio
async def test_handle_tool_call_interception(mock_config):
    # Covers lines 658-690
    scenario = {"id": "test_interceptor"}
    session = SessionManager("run_id", scenario)

    turn_ctx = MagicMock()
    sandbox = AsyncMock()
    sandbox.state = {"a": 1}
    sandbox.get_full_state = AsyncMock(return_value={"a": 1})
    history = []
    actions = {"used_tools": []}

    # 1. Blocked by plugin (664-669)
    session.plugin_manager.trigger_interceptor = MagicMock(return_value=False)
    await session._handle_tool_call(
        1, {"tool_name": "secret_tool"}, sandbox, history, actions, turn_ctx
    )
    assert not sandbox.execute.called

    # 2. Mutated by plugin (672-680)
    session.plugin_manager.trigger_interceptor = MagicMock(
        return_value={"tool_name": "shimmed_tool", "arguments": {"key": "val"}}
    )
    sandbox.execute.return_value = "success"
    await session._handle_tool_call(
        1, {"tool_name": "orig_tool"}, sandbox, history, actions, turn_ctx
    )
    sandbox.execute.assert_called_with("shimmed_tool", {"key": "val"})

    # 3. Short-circuited by plugin (681-689)
    session.plugin_manager.trigger_interceptor = MagicMock(
        return_value={"short_circuit_result": "fast_track"}
    )
    sandbox.execute.reset_mock()
    await session._handle_tool_call(
        1, {"tool_name": "heavy_tool"}, sandbox, history, actions, turn_ctx
    )
    assert not sandbox.execute.called
    assert history[-1]["content"] == "fast_track"


@pytest.mark.asyncio
async def test_agent_response_none_error(mock_config, monkeypatch):
    # Covers lines 456-463 and 501-503
    scenario = {"id": "test_failure", "max_turns": 1}
    session = SessionManager("run_id", scenario)

    sandbox = AsyncMock()
    sandbox.get_full_state = AsyncMock(return_value={})
    # _verify_state_parity should return True to not obscure the error
    session._verify_state_parity = AsyncMock(return_value=True)
    # _calculate_metrics should return a mock result
    session._calculate_metrics = AsyncMock(return_value={"metrics": []})

    # Use monkeypatch for reliability on classmethods
    mock_call = AsyncMock(return_value=None)
    monkeypatch.setattr(eval_runner.engine.AgentAdapterRegistry, "call_agent", mock_call)

    res = await session._execute_node(
        {"id": "node1", "task_description": "test"}, 1, 0, sandbox, [], {"used_tools": []}
    )
    assert res["status"] == "failure"


@pytest.mark.asyncio
async def test_handle_multiple_tools_interception(mock_config):
    # Covers lines 735-767
    scenario = {"id": "test_multi"}
    session = SessionManager("run_id", scenario)

    turn_ctx = MagicMock()
    sandbox = AsyncMock()
    sandbox.state = {"b": 2}
    sandbox.get_full_state = AsyncMock(return_value={"b": 2})
    sandbox.execute.return_value = "ok"
    history = []
    actions = {"used_tools": []}

    # Mix of blocked, mutated, and short-circuited
    def mock_interceptor(hook, context, tool_name, params):
        if tool_name == "blocked":
            return False
        if tool_name == "short":
            return {"short_circuit_result": "shortcut"}
        if tool_name == "mutated":
            return {"tool_name": "real", "arguments": {"x": 1}}
        return None

    session.plugin_manager.trigger_interceptor = MagicMock(side_effect=mock_interceptor)

    agent_response = {"tool_names": ["blocked", "short", "mutated", "normal"]}

    await session._handle_multiple_tools(1, agent_response, sandbox, history, actions, turn_ctx)

    # Check results in history
    results = history[-1]["content"]
    assert results[0]["status"] == "blocked"
    assert results[1] == "shortcut"
    assert "ok" in results[2:]

    # Verify sandbox calls
    sandbox.execute.assert_any_call("real", {"x": 1})
    sandbox.execute.assert_any_call("normal", {})


@pytest.mark.asyncio
async def test_session_fork_limit(mock_config):
    # Covers lines 1048-1049
    from eval_runner.session import MAX_FORK_DEPTH

    scenario = {"id": "test_fork", "_fork_depth": MAX_FORK_DEPTH}
    session = SessionManager("run_id", scenario)

    with pytest.raises(RuntimeError, match="Fork Bomb Prevention"):
        session.fork([], {})
