from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.context import TurnContext
from eval_runner.session import SessionManager
from eval_runner.tool_sandbox import ToolSandbox


@pytest.fixture
def mock_env_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.mark.asyncio
async def test_session_run_empty_topology(mock_env_config):
    # In AES v1.4.0, an empty topology is a fail-fast condition.
    # The session catches this and returns a failure result in the list.
    scenario = {
        "id": "empty",
        "workflow": {"nodes": [], "edges": []},
        "metadata": {},
        "aes_version": 1.4,
        "evaluation": {"metrics": []},
    }
    session = SessionManager("run_empty", scenario)
    results = await session.execute_tasks(1)
    assert len(results) == 1
    assert results[0]["status"] == "failure"
    assert "Empty Topology" in results[0]["message"]


@pytest.mark.asyncio
async def test_session_run_cyclic_graph(mock_env_config):
    # Cyclic graphs are caught by TopologicalSorter and re-raised as industrial ValueErrors.
    # These propagate out of execute_tasks.
    scenario = {
        "id": "cycle",
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "t1"},
                {"id": "n2", "task_description": "t2"},
            ],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n1"}],
        },
        "metadata": {},
        "aes_version": 1.4,
        "evaluation": {"metrics": []},
    }
    session = SessionManager("run_cycle", scenario)
    results = await session.execute_tasks(1)
    assert len(results) == 1
    assert results[0]["status"] == "failure"
    assert "Cyclic dependencies" in results[0]["message"]


@pytest.mark.asyncio
async def test_session_run_fatal_exception(mock_env_config):
    scen_content = {
        "aes_version": 1.4,
        "id": "id1",
        "metadata": {"id": "id1", "name": "n1", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "t1"}], "edges": []},
        "evaluation": {"metrics": []},
    }
    session = SessionManager("run_fatal", scen_content)
    # Patch _execute_node to simulate a crash.
    with patch.object(session, "_execute_node", side_effect=Exception("AUTHORITATIVE_FATAL")):
        results = await session.execute_tasks(1)
        assert len(results) >= 1
        assert any("AUTHORITATIVE_FATAL" in r.get("message", "") for r in results)


@pytest.mark.asyncio
async def test_session_process_response_actions(mock_env_config):
    scen = {
        "id": "t",
        "metadata": {},
        "max_turns": 10,
        "workflow": {"nodes": [], "edges": []},
        "evaluation": {"metrics": []},
        "aes_version": 1.4,
    }
    session = SessionManager("run1", scen)
    sandbox = MagicMock(spec=ToolSandbox)
    sandbox.get_full_state = AsyncMock(return_value={})
    sandbox.state = {}
    history = []
    actions = {"used_tools": []}
    node = {"id": "n1", "task_description": "t1", "expected_outcome": []}
    responses = [
        {"action": "call_multiple_tools", "tool_names": ["t1"]},
        {"action": "call_tool", "tool_name": "t2", "tool_params": {}},
        {"action": "hitl_pause", "prompt": "help"},
        {"action": "processing"},
        {"action": "completed"},
    ]

    # Critical: Patching AgentAdapterRegistry in the session module scope
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            side_effect=responses,
        ) as mock_call,
        patch.object(session, "_handle_multiple_tools", new_callable=AsyncMock),
        patch.object(session, "_handle_tool_call", new_callable=AsyncMock),
        patch.object(session, "_handle_hitl", new_callable=AsyncMock) as mock_hitl,
    ):
        mock_hitl.return_value = "human says hi"

        with (
            patch.object(session, "_verify_state_parity", return_value=True),
            patch.object(session, "_calculate_metrics", new_callable=AsyncMock),
        ):
            await session._execute_node(node, 1, 0, sandbox, history, actions)

            assert mock_call.call_count >= 1
            assert len(history) >= 1


@pytest.mark.asyncio
async def test_session_parity_variants(mock_env_config):
    scen = {"id": "t", "metadata": {}, "aes_version": 1.4, "evaluation": {"metrics": []}}
    session = SessionManager("run1", scen)
    node = {
        "id": "n1",
        "expected_outcome": [
            {"target": "message", "expected": "regex:hello.*world", "mode": "regex"}
        ],
    }
    # History role must be 'agent' for summary extraction
    history = [{"role": "agent", "content": "hello beautiful world"}]
    res1 = await session._verify_state_parity(node, MagicMock(), history)
    assert res1 is True

    history2 = [{"role": "agent", "content": "goodbye"}]
    res2 = await session._verify_state_parity(node, MagicMock(), history2)
    assert res2 is False


@pytest.mark.asyncio
async def test_session_metrics_hygiene_ops(mock_env_config):
    scen = {"id": "t", "metadata": {}, "aes_version": 1.4, "evaluation": {"metrics": []}}
    session = SessionManager("run1", scen)
    session.state_snapshots.append({"state": 1})
    assert len(session.state_snapshots) == 1
    session._capture_telemetry()
    assert session.forensics is not None


@pytest.mark.asyncio
async def test_session_metrics_dispatch(mock_env_config):
    scen = {"id": "t", "metadata": {}, "aes_version": 1.4, "evaluation": {"metrics": []}}
    session = SessionManager("run1", scen)
    # success_criteria is the industrial key for node-level metrics
    node = {"id": "n1", "success_criteria": [{"metric": "m1"}]}
    sandbox = MagicMock(spec=ToolSandbox)
    sandbox.get_full_state = AsyncMock(return_value={})
    sandbox.state = {}

    with patch("eval_runner.session.metrics.MetricRegistry.get") as mock_get:
        # Mocking the metric function itself
        mock_metric = AsyncMock(return_value=1.0)
        mock_get.return_value = mock_metric
        res = await session._calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": []})
        assert len(res["metrics"]) >= 1


@pytest.mark.asyncio
async def test_session_metrics_error_handling(mock_env_config):
    scen = {"id": "t", "metadata": {}, "aes_version": 1.4, "evaluation": {"metrics": []}}
    session = SessionManager("run1", scen)
    node = {"id": "n1", "success_criteria": [{"metric": "m1"}]}
    sandbox = MagicMock(spec=ToolSandbox)
    sandbox.get_full_state = AsyncMock(return_value={})
    sandbox.state = {}

    with patch(
        "eval_runner.session.metrics.MetricRegistry.get", side_effect=Exception("METRIC_FAIL")
    ):
        res = await session._calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": []})
        assert "metrics" in res


@pytest.mark.asyncio
async def test_session_tool_call_logic(mock_env_config):
    scen = {"id": "t", "metadata": {}, "aes_version": 1.4, "evaluation": {"metrics": []}}
    session = SessionManager("run1", scen)
    sandbox = MagicMock(spec=ToolSandbox)
    sandbox.execute = AsyncMock(return_value="tool_output")
    sandbox.get_full_state = AsyncMock(return_value={})
    sandbox.state = {}
    history = []

    resp = {"action": "call_tool", "tool_name": "t1", "tool_params": {"a": 1}}
    ctx = TurnContext("n1", 1, "m", [], None)
    await session._handle_tool_call(1, resp, sandbox, history, {"used_tools": []}, ctx)

    assert any("tool_output" in str(m) for m in history)


@pytest.mark.asyncio
async def test_session_multiple_tools_logic(mock_env_config):
    scen = {"id": "t", "metadata": {}, "aes_version": 1.4, "evaluation": {"metrics": []}}
    session = SessionManager("run1", scen)
    sandbox = MagicMock(spec=ToolSandbox)
    sandbox.execute = AsyncMock(return_value="tool_output")
    sandbox.get_full_state = AsyncMock(return_value={})
    sandbox.state = {}
    resp = {"action": "call_multiple_tools", "tool_names": ["t1", "t2"]}

    ctx = TurnContext("n1", 1, "m", [], None)
    await session._handle_multiple_tools(1, resp, sandbox, [], {"used_tools": []}, ctx)
    assert len(sandbox.execute.call_args_list) == 2


@pytest.mark.asyncio
async def test_session_telemetry_and_forensics(mock_env_config):
    scen = {"id": "t", "metadata": {}, "aes_version": 1.4, "evaluation": {"metrics": []}}
    session = SessionManager("run1", scen)
    session._capture_telemetry()
    assert session.forensics is not None
