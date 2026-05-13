import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.session import SessionManager


@pytest.fixture
def base_scenario():
    return {
        "id": "test_scenario",
        "workflow": {"nodes": [{"id": "node_1", "task_description": "test task"}]},
        "evaluation": {"metrics": [{"metric": "exact_match", "threshold": 0.5}]},
    }


@pytest.mark.asyncio
async def test_session_psutil_missing(base_scenario, tmp_path):
    with patch.dict("sys.modules", {"psutil": None}):
        import eval_runner.session

        importlib.reload(eval_runner.session)
        session = eval_runner.session.SessionManager("test_run", base_scenario, log_root=tmp_path)
        session._capture_telemetry()
        assert len(session.resource_telemetry) == 0
    importlib.reload(eval_runner.session)


@pytest.mark.asyncio
async def test_session_metadata_update(base_scenario, tmp_path):
    session = SessionManager(
        "test_run", base_scenario, metadata={"extra": "data"}, log_root=tmp_path
    )
    assert session.session_metadata["extra"] == "data"


@pytest.mark.asyncio
async def test_session_plugin_load_failure(base_scenario, tmp_path):
    with patch("eval_runner.plugins.PluginManager.load", side_effect=Exception("Load fail")):
        from eval_runner import plugins

        with patch.object(
            plugins.manager, "provenance_map", {"P1": {"origin": "EXTERNAL", "path": "p"}}
        ):
            session = SessionManager("test_run", base_scenario, log_root=tmp_path)
            assert session.run_id == "test_run"


@pytest.mark.asyncio
async def test_session_plugin_archive_failure(base_scenario, tmp_path):
    with patch(
        "eval_runner.forensics.ForensicCollector.archive_plugin",
        side_effect=Exception("Archive fail"),
    ):
        from eval_runner import plugins

        with patch.object(
            plugins.manager, "provenance_map", {"P1": {"origin": "EXTERNAL", "path": "p"}}
        ):
            session = SessionManager("test_run", base_scenario, log_root=tmp_path)
            assert session.run_id == "test_run"


@pytest.mark.asyncio
async def test_session_empty_topology_and_trace_init(base_scenario, tmp_path):
    scenario = {"id": "empty", "workflow": {"nodes": []}}
    session = SessionManager("test_run", scenario, log_root=tmp_path)
    session.event_bus.emit("MANUAL_INIT", {})
    results = await session.execute_tasks(1)
    assert results[0]["status"] == "failure"


@pytest.mark.asyncio
async def test_session_unrecognized_action_and_throttle(base_scenario, tmp_path):

    with patch("eval_runner.config.EVAL_TURN_THROTTLE", 0.01):
        session = SessionManager("test_run", base_scenario, log_root=tmp_path)
        mock_sandbox = AsyncMock()
        mock_sandbox.state = {}
        mock_sandbox.get_full_state.return_value = {}

        with patch(
            "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_agent:
            mock_agent.return_value = {"action": "jump"}
            with patch.object(
                session, "_calculate_metrics", new_callable=AsyncMock
            ) as mock_metrics:
                mock_metrics.return_value = {"metrics": []}
                res = await session._execute_node(
                    base_scenario["workflow"]["nodes"][0], 1, 0, mock_sandbox, [], {}
                )
                assert res["status"] == "failure"


@pytest.mark.asyncio
async def test_session_state_parity_exhaustive(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [
            {"target": "shim:db.table", "expected": "ok"},
            {"target": "state", "property": "n", "expected": 1.0, "mode": "numerical_tolerance"},
            {"target": "message", "expected": "missing", "mode": "exact"},
        ],
        "timeout": 0.1,
    }
    mock_sandbox = MagicMock()
    mock_db = AsyncMock()
    mock_db.get_snapshot.return_value = "ok"
    mock_sandbox.get_active_simulators.return_value = {"db": mock_db}
    mock_sandbox.get_full_state = AsyncMock(return_value={"n": 2.0})

    res = await session._verify_state_parity(
        node, mock_sandbox, [{"role": "agent", "content": "not_missing"}]
    )
    assert res is False


@pytest.mark.asyncio
async def test_session_state_parity_regex_numerical(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [
            {"target": "state", "property": "s", "expected": "regex:hello", "mode": "regex"},
            {"target": "state", "property": "v", "expected": 1.0, "mode": "numerical_tolerance"},
        ],
        "timeout": 0.1,
    }
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = {}
    mock_sandbox.get_full_state = AsyncMock(return_value={"s": "hello world", "v": 1.000000000001})

    res = await session._verify_state_parity(node, mock_sandbox, [])
    assert res is True


@pytest.mark.asyncio
async def test_session_contains_assertion_list(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [{"target": "message", "expected": ["a", "b"], "mode": "contains"}],
        "timeout": 0.1,
    }
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = {}

    res = await session._verify_state_parity(
        node, mock_sandbox, [{"role": "agent", "content": "alpha"}]
    )
    assert res is True
    res = await session._verify_state_parity(
        node, mock_sandbox, [{"role": "agent", "content": "zzz"}]
    )
    assert res is False


@pytest.mark.asyncio
async def test_handle_multiple_tools_exhaustive(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.execute.return_value = {"status": "success"}
    mock_sandbox.get_full_state.return_value = {}

    # Short circuit via interceptor
    with patch.object(
        session.plugin_manager, "trigger_interceptor", return_value={"short_circuit_result": "fast"}
    ):
        agent_resp = {"tool_calls": [{"tool": "t1"}]}
        await session._handle_multiple_tools(
            1, agent_resp, mock_sandbox, [], {"used_tools": []}, MagicMock()
        )

    # Blocked tool
    with patch.object(session.plugin_manager, "trigger_interceptor", return_value=False):
        await session._handle_multiple_tools(
            1, agent_resp, mock_sandbox, [], {"used_tools": []}, MagicMock()
        )


@pytest.mark.asyncio
async def test_calculate_metrics_exhaustive(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "state_hygiene": {"rules": [{"path": "a", "op": "eq", "expected": 1}]},
        "expected_outcome": [{"target": "message", "expected": "goal"}],
        "expected_state_changes": [{"path": "a", "value": 1}],
        "success_criteria": [{"metric": "m1"}],
    }
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {"a": 1}
    session.resource_telemetry = []

    async def metric(forensic_telemetry, expected, expected_state_changes):
        return (
            1.0
            if forensic_telemetry is not None and expected == "goal" and expected_state_changes
            else 0.0
        )

    with patch("eval_runner.metrics.MetricRegistry.get", return_value=metric):
        with patch("eval_runner.metrics.MetricRegistry.get_source", return_value="CORE"):
            res = await session._calculate_metrics(node, 1, 1, [], mock_sandbox, {"used_tools": []})
            assert res["metrics"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_session_history_duplication_fix(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    session.scenario["workflow"] = {
        "nodes": [{"id": "n1", "task_description": "t1"}, {"id": "n2", "task_description": "t2"}],
        "edges": [{"from": "n1", "to": "n2"}],
    }
    session.scenario["evaluation"] = {"metrics": [{"metric": "m1"}]}
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}
    mock_sandbox.setup = AsyncMock()
    mock_sandbox.teardown = AsyncMock()

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.return_value = {"action": "completed"}

        async def dummy_metric(*args, **kwargs):
            return 1.0

        with patch("eval_runner.metrics.MetricRegistry.get", return_value=dummy_metric):
            with patch("eval_runner.metrics.MetricRegistry.get_source", return_value="CORE"):
                results = await session.execute_tasks(1)
                global_res = next(r for r in results if r["task_id"] == "global_evaluation")
                assert len(global_res["conversation_history"]) == 4


@pytest.mark.asyncio
async def test_session_telemetry_error_branch(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    with patch("psutil.Process", side_effect=Exception("Fatal Tele")):
        session._capture_telemetry()
