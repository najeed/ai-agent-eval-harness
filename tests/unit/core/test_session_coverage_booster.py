from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.session import SessionManager


@pytest.fixture
def base_scenario():
    return {
        "id": "test_scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "task_description": "test task",
                    "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
                }
            ]
        },
        "evaluation": {"metrics": [{"metric": "exact_match", "threshold": 0.5}]},
    }


@pytest.mark.asyncio
async def test_session_psutil_missing(base_scenario, tmp_path):
    with patch("eval_runner.session.psutil", None):
        session = SessionManager("test_run", base_scenario, log_root=tmp_path)
        session._capture_telemetry()
        assert len(session.resource_telemetry) == 0


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

    res, _ev = await session._verify_state_parity(
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

    res, _ev = await session._verify_state_parity(node, mock_sandbox, [])
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

    res, _ev = await session._verify_state_parity(
        node, mock_sandbox, [{"role": "agent", "content": "alpha"}]
    )
    assert res is True
    res, _ev = await session._verify_state_parity(
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
        "nodes": [
            {
                "id": "n1",
                "task_description": "t1",
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            },
            {
                "id": "n2",
                "task_description": "t2",
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            },
        ],
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


@pytest.mark.asyncio
async def test_session_turn_number_and_checkpoint_branches(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    # 1. Turn number when turn_state_manager is None
    session.turn_state_manager = None
    session.turn_number = 5
    assert session.turn_number == 5

    # 2. Restore from empty checkpoint
    session.checkpoint_manager.load_latest_checkpoint = MagicMock(return_value=None)
    assert session.restore_from_checkpoint() is False

    # 3. Restore with metadata and session_metadata
    chk_data = {
        "turn": "3",
        "metadata": {"custom_meta": 123},
        "session_metadata": {"extra_meta": 456},
    }
    assert session.restore_from_checkpoint(chk_data) is True
    assert session.turn_number == 3
    assert session.session_metadata["custom_meta"] == 123
    assert session.session_metadata["extra_meta"] == 456


@pytest.mark.asyncio
async def test_session_execute_tasks_cancellation_branch(base_scenario, tmp_path):
    import threading

    cancel_evt = threading.Event()
    cancel_evt.set()

    session = SessionManager(
        "test_run", base_scenario, log_root=tmp_path, cancellation_event=cancel_evt
    )
    session.scenario["workflow"] = {
        "nodes": [
            {
                "id": "node_cancel",
                "task_description": "task",
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            }
        ],
    }

    mock_sandbox = AsyncMock()
    mock_sandbox.setup = AsyncMock()
    mock_sandbox.teardown = AsyncMock()

    with patch("eval_runner.session.ToolSandbox", return_value=mock_sandbox):
        results = await session.execute_tasks(1)
        assert results[0]["status"] == "aborted"
        assert results[0]["message"] == "Execution cancelled"


@pytest.mark.asyncio
async def test_session_hitl_non_interactive_approval_and_rejection(
    base_scenario, tmp_path, monkeypatch
):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    monkeypatch.setenv("FORCE_HITL_SUSPEND", "1")
    monkeypatch.delenv("CI", raising=False)

    class MockApproval:
        def __init__(self, action, response):
            self.action = action
            self.response = response

        async def wait(self):
            pass

    turn_ctx = MagicMock(task_id="task_1")

    # 1. Non-interactive approve
    with (
        patch("sys.stdin.isatty", return_value=False),
        patch.object(
            session.approval_manager,
            "request_approval",
            return_value=MockApproval("approve", "Approved by reviewer"),
        ),
    ):
        res = await session._handle_hitl(1, {"prompt": "Please confirm transfer"}, [], {}, turn_ctx)
        assert res == "Approved by reviewer"

    # 2. Non-interactive reject
    with (
        patch("sys.stdin.isatty", return_value=False),
        patch.object(
            session.approval_manager,
            "request_approval",
            return_value=MockApproval("reject", "Violates policy"),
        ),
    ):
        with pytest.raises(InterruptedError, match="Human reviewer rejected"):
            await session._handle_hitl(1, {"prompt": "Please confirm transfer"}, [], {}, turn_ctx)


def test_runner_dependency_graph_and_run_scenario():
    from agentv_runtime.config import ResolvedRuntimeConfig
    from eval_runner.runner import DefaultRunner, run_scenario

    runner = DefaultRunner()
    mock_store = MagicMock()
    mock_resolver = MagicMock()
    mock_artifact = MagicMock()
    mock_chk = MagicMock()
    mock_policy = MagicMock()
    mock_signer = MagicMock()

    # Test setting dependency graph with dict and ResolvedRuntimeConfig
    runner.set_dependency_graph(
        run_store=mock_store,
        config_resolver=mock_resolver,
        artifact_store=mock_artifact,
        checkpoint_store=mock_chk,
        policy_evaluator=mock_policy,
        signing_backend=mock_signer,
        resolved_config={"timeout_seconds": 60},
    )
    assert runner.run_store is mock_store
    assert runner.artifact_store is mock_artifact

    cfg = ResolvedRuntimeConfig(timeout_seconds=90)
    runner.set_dependency_graph(resolved_config=cfg)
    assert runner.resolved_config.timeout_seconds == 90

    # Test run_scenario with custom runner having set_dependency_graph
    async def fake_run(*args, **kwargs):
        return MagicMock()

    with patch.object(runner, "run", side_effect=fake_run):
        res = run_scenario(
            {"id": "scen_test", "workflow": {"nodes": []}},
            runner=runner,
            run_store=mock_store,
        )
        assert res is not None
