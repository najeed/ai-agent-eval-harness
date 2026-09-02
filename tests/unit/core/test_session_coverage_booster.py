import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.execution_ir import (
    CompiledEvaluationPlan,
    CompiledOracle,
    ExecutionIdentity,
)
from eval_runner.session import ExecutionMode, NodeVerdict, SessionManager, _InterpreterEventBridge
from eval_runner.workflow_interpreter import WorkflowOutcome, WorkflowStatus


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


def test_session_save_and_restore_checkpoint(tmp_path):
    run_id = "run-checkpoint-001"
    scenario = {"id": "s1", "title": "Scenario 1", "turns": []}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    session.turn_number = 3
    session.metadata["test_key"] = "test_val"

    ckpt_id = session.save_checkpoint(checkpoint_id="ckpt_1", metadata={"custom": "data"})
    assert ckpt_id is not None

    session.turn_number = 0
    ok = session.restore_from_checkpoint(checkpoint_data={"turn": 5})
    assert ok is True
    assert session.turn_number == 5


@pytest.mark.asyncio
async def test_session_reconciliation_live_and_hybrid(tmp_path):
    """LIVE/HYBRID reconciliation records."""
    run_id = "run-reconciliation-001"
    scenario = {
        "id": "s_reconcile",
        "title": "Reconcile Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Hello",
                    "expected_outcome": [{"target": "state", "property": "counter", "expected": 1}],
                    "success_criteria": [{"metric": "exact_match", "expected": "completed"}],
                }
            ]
        },
    }
    session = SessionManager(
        run_id,
        scenario,
        metadata={"execution_mode": "live"},
        log_root=tmp_path / "runs",
    )
    session.execution_mode = ExecutionMode.LIVE

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch(
            "eval_runner.tool_sandbox.ToolSandbox.get_full_state",
            new_callable=AsyncMock,
            return_value={"counter": 1},
        ),
    ):
        results = await session.execute_tasks(1)
        assert len(results) >= 1
        node_res = next((r for r in results if r.get("task_id") == "node_1"), None)
        assert node_res is not None
        assert "reconciliation" in node_res
        assert node_res["reconciliation"]["execution_mode"] == "live"


@pytest.mark.asyncio
async def test_session_cancellation_branches(tmp_path):
    """Cancellation in _executor and _execute_node."""
    run_id = "run-cancel-001"
    scenario = {
        "id": "s_cancel",
        "title": "Cancel Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Hello",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session.cancellation_event = threading.Event()
    session.cancellation_event.set()

    results = await session.execute_tasks(1)
    assert len(results) >= 1

    # In turn loop
    session2 = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session2.cancellation_event = threading.Event()
    node_def = {"id": "node_1", "prompt": "Hi"}
    session2.cancellation_event.set()
    res_turn = await session2._execute_node(
        node_def,
        1,
        0,
        session2.tool_sandbox if hasattr(session2, "tool_sandbox") else MagicMock(),
        [],
        {},
    )
    assert res_turn is not None


@pytest.mark.asyncio
async def test_session_state_capture_exceptions(tmp_path):
    """State before/after exception handling."""
    run_id = "run-state-exc-001"
    scenario = {
        "id": "s_state_exc",
        "title": "State Exc Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Hello",
                    "expected_outcome": {"target": "state", "property": "counter", "expected": 1},
                    "success_criteria": [{"metric": "exact_match", "expected": "completed"}],
                }
            ]
        },
    }
    session = SessionManager(
        run_id,
        scenario,
        metadata={"execution_mode": "live"},
        log_root=tmp_path / "runs",
    )
    session.execution_mode = ExecutionMode.LIVE

    # Raising inside get_full_state on the sandbox
    with (
        patch(
            "eval_runner.tool_sandbox.ToolSandbox.get_full_state",
            side_effect=RuntimeError("State capture error"),
        ),
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
    ):
        results = await session.execute_tasks(1)
        assert len(results) >= 1


def test_session_build_verification_decision_missing_oracles(tmp_path):
    """Missing oracles check."""
    run_id = "run-missing-oracles"
    scenario = {"id": "s_missing", "title": "Missing Oracles", "workflow": {"nodes": []}}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    identity = ExecutionIdentity(
        evaluation_run_id=run_id,
        scenario_version_id="1.0.0",
        case_id="case_1",
        attempt_id="attempt_1",
        attempt_number=1,
    )
    outcome = WorkflowOutcome(status=WorkflowStatus.COMPLETED, reason="ok")
    task_results = [
        {
            "task_id": "node_1",
            "metrics": [{"metric": "other_metric", "passed": True}],
        }
    ]

    decision = session._build_verification_decision(
        outcome,
        task_results,
        identity,
        required_oracles=["node_1:sc:required_metric"],
    )
    assert decision["decision"] == "EVALUATION_INVALID"
    assert any(
        "Required oracle 'node_1:sc:required_metric' was missing" in b for b in decision["because"]
    )


@pytest.mark.asyncio
async def test_session_evaluate_consensus_model_shorthand(tmp_path):
    """Judge config with 'model' key."""
    run_id = "run-judge-model"
    scenario = {"id": "s_judge", "title": "Judge", "workflow": {"nodes": []}}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session._last_transition_expectations = ["Hello Expected"]

    panel = [{"model": "gemini-1.5-flash", "provider": "mock"}]
    res = await session._evaluate_consensus({"consensus": {"panel": panel}}, [])
    assert res is not None


@pytest.mark.asyncio
async def test_session_consensus_inconclusive(tmp_path):
    """Consensus INCONCLUSIVE."""
    run_id = "run-consensus-001"
    scenario = {
        "id": "s_consensus",
        "title": "Consensus Scenario",
        "evaluation": {"consensus": {"panel": ["judge_1", "judge_2"], "ija_threshold": 0.8}},
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Test",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    inconclusive_consensus = {
        "status": "INCONCLUSIVE",
        "evaluated": True,
        "agreement": 0.5,
    }

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session,
            "_evaluate_consensus",
            new_callable=AsyncMock,
            return_value=inconclusive_consensus,
        ),
    ):
        results = await session.execute_tasks(1)
        verdict_node = next(
            r for r in results if r.get("synthetic") or r.get("verification_decision")
        )
        assert verdict_node["verification_decision"]["decision"] == "INCONCLUSIVE"
        assert any(
            "Judge panel disagreement" in b
            for b in verdict_node["verification_decision"]["because"]
        )


@pytest.mark.asyncio
async def test_session_fatal_forensic_exception(tmp_path):
    """Fatal forensic exception."""
    from eval_runner.workflow_interpreter import WorkflowInterpreter

    run_id = "run-fatal-001"
    scenario = {
        "id": "s_fatal",
        "title": "Fatal Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Test",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    with patch.object(
        WorkflowInterpreter, "run", side_effect=RuntimeError("Unrecoverable Node Crash")
    ):
        crash_results = await session.execute_tasks(1)
        fatal_node = next(r for r in crash_results if r.get("triage_tag") == "FATAL_ENGINE_ERROR")
        assert "Forensic Exception during node execution" in fatal_node["message"]


def test_session_last_agent_summary_branches():
    # Summary with string message
    h_str = [{"role": "user", "content": "hi"}, {"role": "agent", "content": "Agent replied hello"}]
    assert SessionManager._last_agent_summary(h_str) == "Agent replied hello"

    # Summary with dict message variants
    h_dict_summary = [{"role": "agent", "content": {"summary": "Summary text"}}]
    assert SessionManager._last_agent_summary(h_dict_summary) == "Summary text"

    h_dict_content = [{"role": "agent", "content": {"content": "Content text"}}]
    assert SessionManager._last_agent_summary(h_dict_content) == "Content text"

    h_dict_msg = [{"role": "agent", "content": {"message": "Message text"}}]
    assert SessionManager._last_agent_summary(h_dict_msg) == "Message text"

    # Empty/no agent message
    assert SessionManager._last_agent_summary([]) == ""
    assert SessionManager._last_agent_summary([{"role": "user", "content": "hi"}]) == ""

    # Delegated extract_agent_summary
    assert session_summary_test() == "ok"


def session_summary_test():
    s = SessionManager("r1", {"id": "s1", "title": "t"})
    res = s._extract_agent_summary([{"role": "agent", "content": "ok"}])
    return res


def test_interpreter_event_bridge_exception():
    """_InterpreterEventBridge exception emission."""
    mock_bus = MagicMock()
    mock_bus.emit.side_effect = RuntimeError("Bus failure")

    bridge = _InterpreterEventBridge(mock_bus)
    bridge.emit("test_event", {"data": 123})
    assert bridge.emission_failures == 1


@pytest.mark.asyncio
async def test_session_oracle_evaluation_matrix_outcomes(tmp_path):
    """Oracle matrix and verdict triage branches."""
    run_id = "run-oracle-matrix"
    scenario = {"id": "s_oracles", "title": "Oracle Matrix", "nodes": []}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    # 1. NodeVerdict overall triage tags
    v_invalid = NodeVerdict(
        execution="success", verification="invalid", policy="pass", parity="pass"
    )
    assert v_invalid.overall == "evaluation_invalid"

    v_policy_denied = NodeVerdict(
        execution="success", verification="pass", policy="denied", parity="pass"
    )
    assert v_policy_denied.overall == "policy_denied"

    v_parity_fail = NodeVerdict(
        execution="success", verification="pass", policy="pass", parity="fail"
    )
    assert v_parity_fail.overall == "parity_failed"

    # 2. Session fork
    forked = session.fork(history=[{"role": "agent", "content": "hi"}], sandbox_state={"k": "v"})
    assert forked.run_id == run_id
    assert forked.turn_state_manager.history[0]["content"] == "hi"

    # 3. Direct execution of _execute_node branches for 100% oracle logic coverage
    node_oracle_test = {
        "id": "node_oracle_test",
        "prompt": "Test Prompt",
        "expected_outcome": {"target": "state", "property": "k", "expected": "v"},
        "success_criteria": [{"metric": "exact_match", "expected": "test"}],
    }

    # Branch: Plan reqs missing oracle result
    oracle_unseen = CompiledOracle(
        oracle_id="node_oracle_test:sc:unseen",
        scenario_node_id="node_oracle_test",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
    )
    plan_with_missing_req = CompiledEvaluationPlan(
        oracles={"node_oracle_test:sc:unseen": oracle_unseen},
        node_oracles={"node_oracle_test": [oracle_unseen]},
    )

    mock_sandbox = MagicMock()
    mock_sandbox.get_full_state = AsyncMock(return_value={"k": "v"})
    mock_sandbox.policy_decisions = [{"decision": "DENY", "id": "pol_deny_1"}]

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        res = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_with_missing_req},
        )
        assert res is not None

    # Branch: NOT_APPLICABLE not allowed
    oracle_na_disallowed = CompiledOracle(
        oracle_id="node_oracle_test:sc:exact_match",
        scenario_node_id="node_oracle_test",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
        definition={"allow_not_applicable": False},
    )
    plan_na_disallowed = CompiledEvaluationPlan(
        oracles={"node_oracle_test:sc:exact_match": oracle_na_disallowed},
        node_oracles={"node_oracle_test": [oracle_na_disallowed]},
    )

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "NOT_APPLICABLE"}],
            },
        ),
    ):
        res_na_disallowed = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_na_disallowed},
        )
        assert res_na_disallowed is not None

    # Branch: NOT_APPLICABLE allowed
    oracle_na_allowed = CompiledOracle(
        oracle_id="node_oracle_test:sc:exact_match",
        scenario_node_id="node_oracle_test",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
        definition={"allow_not_applicable": True},
    )
    plan_na_allowed = CompiledEvaluationPlan(
        oracles={"node_oracle_test:sc:exact_match": oracle_na_allowed},
        node_oracles={"node_oracle_test": [oracle_na_allowed]},
    )

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "NOT_APPLICABLE"}],
            },
        ),
    ):
        res_na_ok = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_na_allowed},
        )
        assert res_na_ok is not None

    # Branch: Policy denied overall
    mock_sandbox_policy_fail = MagicMock()
    mock_sandbox_policy_fail.get_full_state = AsyncMock(return_value={"k": "v"})
    mock_sandbox_policy_fail.policy_decisions = []

    async def _add_policy_denial(*args, **kwargs):
        mock_sandbox_policy_fail.policy_decisions.append({"decision": "denied", "id": "pol_deny_1"})
        return {"action": "completed"}

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            side_effect=_add_policy_denial,
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "PASS"}],
            },
        ),
    ):
        res_pol_denied = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox_policy_fail,
            [],
            {},
            execution_context={},
        )
        assert res_pol_denied.get("triage_tag") == "POLICY_DENIED"

    # Branch: Parity failed overall
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session,
            "_verify_state_parity",
            new_callable=AsyncMock,
            return_value=(False, [{"passed": False, "assertion": {"target": "state"}}]),
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "PASS"}],
            },
        ),
    ):
        res_parity_fail = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_parity_fail is not None

    # Branch: Fallback branch without plan reqs with REQUIRED oracles
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "exact_match", "outcome": "FAIL", "requiredness": "REQUIRED"},
                ],
            },
        ),
    ):
        res_fallback = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_fallback is not None

    # Fallback branch: all NOT_APPLICABLE
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {
                        "metric": "exact_match",
                        "outcome": "NOT_APPLICABLE",
                        "requiredness": "REQUIRED",
                    },
                ],
            },
        ),
    ):
        res_all_na = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_all_na is not None

    # Branch: Plan reqs all NOT_APPLICABLE
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "NOT_APPLICABLE"}],
            },
        ),
    ):
        res_plan_all_na = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_na_allowed},
        )
        assert res_plan_all_na.get("node_verdict", {}).get("verification") == "pass"

    # Branch: Fallback branch with non-REQUIRED oracle fail -> verification = fail
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "exact_match", "outcome": "FAIL", "requiredness": "OPTIONAL"},
                ],
            },
        ),
    ):
        res_optional_fail = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_optional_fail.get("node_verdict", {}).get("verification") == "pass"

    # Empty node_oracle_results -> not_applicable
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session, "_verify_state_parity", new_callable=AsyncMock, return_value=(True, [])
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [],
            },
        ),
    ):
        res_empty = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_empty.get("node_verdict", {}).get("verification") == "not_applicable"


@pytest.mark.asyncio
async def test_session_executor_cancellation_and_empty_results(tmp_path):
    """Cancellation in _executor and empty task results fallback."""
    run_id = "run-cancel-executor"
    scenario = {
        "id": "s_cancel_exec",
        "title": "Cancel Exec",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Test",
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session.cancellation_event = threading.Event()
    session.cancellation_event.set()

    results = await session.execute_tasks(1)
    assert len(results) >= 1

    # Empty all_task_results fallback
    session2 = SessionManager("run-empty-results", scenario, log_root=tmp_path / "runs")
    from eval_runner.workflow_interpreter import WorkflowOutcome, WorkflowStatus

    mock_outcome = WorkflowOutcome(status=WorkflowStatus.COMPLETED, reason="ok")
    with patch(
        "eval_runner.workflow_interpreter.WorkflowInterpreter.run",
        new_callable=AsyncMock,
        return_value=([], mock_outcome),
    ):
        results_empty = await session2.execute_tasks(1)
        assert len(results_empty) >= 1
        assert any(r.get("task_id") == "workflow_verdict" for r in results_empty)
