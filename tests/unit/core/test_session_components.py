"""
tests/unit/core/test_session_components.py

Comprehensive test suite verifying 100% statement and branch coverage across all
decomposed session components under `eval_runner/session_components/`:
- SessionMetricsCalculator
- SessionStateParityVerifier
- SessionApprovalManager
- SessionCheckpointManager
- TurnStateManager
- ToolExecutionCoordinator
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import eval_runner.metrics as metrics
from eval_runner.events import EventEmitter
from eval_runner.session_components import (
    SessionApprovalManager,
    SessionCheckpointManager,
    SessionMetricsCalculator,
    SessionStateParityVerifier,
    ToolExecutionCoordinator,
    TurnStateManager,
)


@pytest.mark.asyncio
async def test_session_metrics_calculator_comprehensive():
    event_bus = EventEmitter(run_id="run-calc-001")
    mock_sm = MagicMock()
    mock_sm.event_bus = event_bus
    mock_sm.session_metadata = {"span_context": {"trace_id": "t1"}}
    mock_sm.protocol_sequence = ["init", "exec"]
    mock_sm.state_snapshots = []
    mock_sm.resource_telemetry = []
    mock_sm._extract_tool_registry.return_value = {"tool1": {}}
    mock_sm.identifier = "test_scenario"
    mock_sm.max_turns = 5
    mock_sm.scenario = {"metadata": {"name": "Test"}}
    mock_sm.plugin_manager.provenance_map = {
        "CORE": {"trusted": True},
        "custom_ext": {"trusted": False},
    }

    calc = SessionMetricsCalculator(session_manager=mock_sm)

    # 1. extract_agent_summary coverage
    assert calc.extract_agent_summary([]) == ""
    assert calc.extract_agent_summary([{"role": "user", "content": "hi"}]) == ""
    assert calc.extract_agent_summary([{"role": "agent", "content": "Done"}]) == "Done"
    assert (
        calc.extract_agent_summary([{"role": "agent", "content": {"summary": "Completed order"}}])
        == "Completed order"
    )
    assert (
        calc.extract_agent_summary([{"role": "agent", "content": {"instructions": "Follow steps"}}])
        == "Follow steps"
    )
    assert (
        calc.extract_agent_summary([{"role": "agent", "content": {"message": "Message text"}}])
        == "Message text"
    )
    assert (
        calc.extract_agent_summary([{"role": "agent", "content": {"content": "Direct text"}}])
        == "Direct text"
    )
    assert calc.extract_agent_summary([{"role": "agent", "content": {"other": "val"}}]) == ""

    # 2. Register custom sync and async metrics for dispatch testing
    @metrics.MetricRegistry.register("test_sync_metric", source="CORE")
    def custom_sync_metric(history, actual_state, used_tools, turns_taken, metadata):
        assert isinstance(history, list)
        return 1.0

    @metrics.MetricRegistry.register("test_async_metric", source="custom_ext")
    async def custom_async_metric(
        summary, actual, expected, attempt_number, history, sandbox_state
    ):
        # history and sandbox_state are isolated deep copies for untrusted source
        assert isinstance(history, list)
        assert isinstance(sandbox_state, dict)
        return 0.95

    @metrics.MetricRegistry.register("test_faulty_metric", source="CORE")
    def faulty_metric(nonexistent_param):
        raise RuntimeError("Metric failed intentionally")

    mock_sandbox = MagicMock()
    mock_sandbox.state = {
        "status": "active",
        "nested": {"count": 10},
        "tags": ["prod", "secure"],
        "empty_list": [],
    }

    node = {
        "id": "node_1",
        "state_hygiene": {
            "rules": [
                {"path": "status", "expected": "active", "op": "eq"},
                {"path": "status", "expected": "inactive", "op": "eq"},  # false eq
                {"path": "nested.count", "op": "exists"},
                {"path": "missing_field", "op": "exists"},  # false exists
                {"path": "missing_field", "op": "not_exists"},
                {"path": "status", "op": "not_exists"},  # false not_exists
                {"path": "tags", "expected": "prod", "op": "contains"},
                {"path": "empty_list", "expected": "item", "op": "contains"},  # false contains
            ]
        },
        "expected_outcome": [{"target": "message", "expected": "All tasks done"}],
        "success_criteria": [
            {"metric": "test_sync_metric", "threshold": 0.8},
            {"metric": "test_async_metric", "threshold": 0.9},
            {"metric": "unknown_metric_skipped", "threshold": 1.0},
            {"metric": "test_faulty_metric", "threshold": 1.0},
        ],
    }

    history = [
        {"role": "user", "content": "Start"},
        {"role": "agent", "content": "All tasks done", "agent_id": "main_agent"},
    ]
    actions = {"used_tools": ["tool1"]}

    res = await calc.calculate_metrics(
        node=node,
        attempt_number=1,
        turns=2,
        history=history,
        sandbox=mock_sandbox,
        actions=actions,
    )

    assert res["task_id"] == "node_1"
    assert "state_hygiene" in res
    # Strict assertion semantics: unknown/exception-producing
    # metrics are recorded as EVALUATION_INVALID rows, never silently skipped.
    assert len(res["metrics"]) == 4
    assert res["metrics"][0]["metric"] == "test_sync_metric"
    assert res["metrics"][0]["success"] is True
    assert res["metrics"][1]["metric"] == "test_async_metric"
    assert res["metrics"][1]["success"] is True
    assert res["metrics"][2]["metric"] == "unknown_metric_skipped"
    assert res["metrics"][2]["status"] == "EVALUATION_INVALID"
    assert res["metrics"][2]["success"] is False
    assert res["metrics"][3]["metric"] == "test_faulty_metric"
    assert res["metrics"][3]["status"] == "EVALUATION_INVALID"

    # Required hygiene rule failures gate the node (evaluation invalid)
    assert res["evaluation_valid"] is False
    assert res["triage_tag"] == "EVALUATION_INVALID"
    assert any("state_hygiene" in r for r in res["invalid_reasons"])
    assert any("unknown_metric_skipped" in r for r in res["invalid_reasons"])
    assert any("test_faulty_metric" in r for r in res["invalid_reasons"])


@pytest.mark.asyncio
async def test_session_state_parity_verifier_comprehensive():
    mock_sm = MagicMock()
    mock_sm.event_bus = EventEmitter(run_id="run-parity-001")
    mock_sm._extract_agent_summary.return_value = "Agent completed with score 99.5"

    verifier = SessionStateParityVerifier(session_manager=mock_sm)

    # 1. Empty assertions & empty shim_ids
    passed, _ev = await verifier.verify_state_parity({}, None, [])
    assert passed is True
    assert await verifier.get_shim_snapshots(MagicMock(), []) == {}

    # 2. Coroutine-based get_snapshot and get_state, sync state, and missing shim
    async def async_snap():
        return {"val": 42, "data": {"val": 42}}

    async def async_state():
        return {"ready": True}

    mock_sim1 = MagicMock()
    mock_sim1.get_snapshot = async_snap
    del mock_sim1.get_state

    mock_sim2 = MagicMock()
    mock_sim2.get_state = async_state
    del mock_sim2.get_snapshot

    mock_sim3 = MagicMock()
    mock_sim3.get_snapshot.return_value = {"sync_snap": True}
    del mock_sim3.get_state

    mock_sim4 = MagicMock()
    mock_sim4.get_state.return_value = {"sync_state": True}
    del mock_sim4.get_snapshot

    mock_sim5 = MagicMock()
    mock_sim5.state = {"raw_state": True}
    del mock_sim5.get_snapshot
    del mock_sim5.get_state

    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = {
        "s1": mock_sim1,
        "s2": mock_sim2,
        "s3": mock_sim3,
        "s4": mock_sim4,
        "s5": mock_sim5,
    }
    mock_sandbox.get_full_state = AsyncMock(return_value={"version": "1.0"})

    snaps = await verifier.get_shim_snapshots(
        mock_sandbox, ["s1", "s2", "s3", "s4", "s5", "missing_shim"]
    )
    assert snaps["s1"] == {"val": 42, "data": {"val": 42}}
    assert snaps["s2"] == {"ready": True}
    assert snaps["s3"] == {"sync_snap": True}
    assert snaps["s4"] == {"sync_state": True}
    assert snaps["s5"] == {"raw_state": True}

    # 3. All assertion comparison modes
    node_pass = {
        "timeout": 2.0,
        "expected_outcome": [
            {"target": "shim:s1.val", "expected": 42, "mode": "exact"},
            {"target": "shim:s1.data", "property": "val", "expected": 42, "mode": "exact"},
            {"target": "shim:s2", "property": "ready", "expected": True, "mode": "exact"},
            {"target": "message", "expected": "regex:score 99", "mode": "regex"},
            {"target": "message", "expected": ["completed", "done"], "mode": "contains"},
            {"target": "message", "expected": "completed", "mode": "contains"},
            {"target": "state", "property": "version", "expected": "1.0", "mode": "exact"},
        ],
    }
    passed, _ev = await verifier.verify_state_parity(node_pass, mock_sandbox, [])
    assert passed is True

    # 4. Numerical tolerance mode (match, mismatch, non-float)
    node_tol = {
        "timeout": 0.5,
        "expected_outcome": [
            {"target": "shim:s1.val", "expected": 42.00000000001, "mode": "numerical_tolerance"},
        ],
    }
    passed, _ev = await verifier.verify_state_parity(node_tol, mock_sandbox, [])
    assert passed is True

    node_tol_fail = {
        "timeout": 0.2,
        "expected_outcome": [
            {"target": "shim:s1.val", "expected": "not_a_number", "mode": "numerical_tolerance"},
        ],
    }
    passed, _ev = await verifier.verify_state_parity(node_tol_fail, mock_sandbox, [])
    assert passed is False

    # 5. Unsupported target and timeout divergence
    node_unsupported = {
        "timeout": 0.2,
        "expected_outcome": [
            {"target": "unsupported_target_type", "expected": 123},
        ],
    }
    passed, _ev = await verifier.verify_state_parity(node_unsupported, mock_sandbox, [])
    assert passed is False

    # 6. Tolerance parsing fallback with invalid string and unsupported mode
    node_bad_tol = {
        "expected_outcome": [
            {
                "target": "message",
                "property": "",
                "expected": "hi",
                "mode": "unsupported_mode",
                "tolerance": "bad_tol",
            },
        ]
    }
    passed_mode, _ = await verifier.verify_state_parity(
        node_bad_tol,
        mock_sandbox,
        [{"role": "assistant", "content": "hi"}],
    )
    assert passed_mode is False

    # 7. Agent summary extraction failure handling
    mock_session_failing = MagicMock()
    mock_session_failing._extract_agent_summary.side_effect = RuntimeError("Summary crash")
    verifier_fail = SessionStateParityVerifier(session_manager=mock_session_failing)
    passed_sum, _ = await verifier_fail.verify_state_parity(
        {"expected_outcome": [{"target": "message", "expected": "hello"}]}, mock_sandbox, []
    )
    assert passed_sum is False

    # 8. State before value resolution
    mock_state_box = MagicMock()
    mock_state_box.get_full_state = AsyncMock(return_value={"user": {"name": "Alice"}})
    node_state_before = {
        "expected_outcome": [
            {"target": "state", "property": "user.name", "expected": "Alice", "mode": "exact"},
            {"target": "state", "expected": {"user": {"name": "Alice"}}, "mode": "exact"},
        ]
    }
    passed_before, ev_before = await verifier.verify_state_parity(
        node_state_before, mock_state_box, [], state_before={"user": {"name": "Bob"}}
    )
    assert passed_before is True
    assert ev_before[0]["actual_before"] == "Bob"
    assert ev_before[1]["actual_before"] == {"user": {"name": "Bob"}}


@pytest.mark.asyncio
async def test_tool_execution_coordinator_all_branches():
    # 1. With sandbox
    mock_sandbox = MagicMock()
    mock_sandbox.execute_tool.return_value = {"output": "sandbox_exec"}
    coord1 = ToolExecutionCoordinator(sandbox=mock_sandbox)
    res1 = coord1.execute("sandbox_tool", {"arg": "val"})
    assert res1 == {"output": "sandbox_exec"}
    assert coord1.executed_tools[0]["status"] == "success"

    # 2. With handler
    def custom_handler(x, y):
        return x + y

    coord2 = ToolExecutionCoordinator()
    res2 = coord2.execute("add", {"x": 10, "y": 20}, handler=custom_handler)
    assert res2 == 30

    # 3. Fallback
    coord3 = ToolExecutionCoordinator()
    res3 = coord3.execute("echo", {"text": "hi"})
    assert "Executed echo" in res3["result"]
    snap3 = coord3.snapshot()
    assert snap3["executed_count"] == 1
    assert snap3["tool_names"] == ["echo"]

    # 4. Exception propagation and record status
    def fail_handler():
        raise ValueError("Handler explosion")

    coord4 = ToolExecutionCoordinator()
    with pytest.raises(ValueError, match="Handler explosion"):
        coord4.execute("boom", {}, handler=fail_handler)
    assert coord4.executed_tools[0]["status"] == "error"


@pytest.mark.asyncio
async def test_checkpoint_and_turn_state_managers(tmp_path):
    from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore

    db_path = str(tmp_path / "chk_mgr.db")
    store = SQLiteCheckpointStore(db_path=db_path)
    chk_mgr = SessionCheckpointManager(run_id="run-mgr-001", store=store)

    chk_id = chk_mgr.create_checkpoint({"turn": 1, "step": "init"}, metadata={"tag": "v1"})
    assert chk_id is not None

    latest = chk_mgr.load_latest_checkpoint()
    assert latest is not None
    assert latest["turn"] == 1

    all_chks = chk_mgr.list_checkpoints()
    assert len(all_chks) >= 1

    # Lazy store instantiation
    lazy_chk_mgr = SessionCheckpointManager(run_id="run-mgr-lazy")
    assert lazy_chk_mgr.store is not None

    # Approval manager lifecycle and faulty state provider
    def faulty_state():
        raise RuntimeError("State capture failed")

    app_mgr = SessionApprovalManager(
        run_id="run-mgr-001",
        checkpoint_manager=chk_mgr,
        state_provider=faulty_state,
    )
    app = app_mgr.request_approval("t1", "transfer", {"amt": 100})
    assert app is not None

    pending = app_mgr.list_pending_approvals()
    assert any(p.id == app.id for p in pending)

    res = app_mgr.resolve_approval(app.id, "approve", response="OK", resolved_by="auditor")
    assert res is True

    # TurnStateManager restore with history and tokens
    tsm = TurnStateManager(max_turns=10)
    assert tsm.is_exhausted() is False
    t1 = tsm.start_turn()
    assert t1 == 1
    tsm.start_turn(turn_number=5)
    assert tsm.current_turn == 5
    tsm.start_turn(turn_number=10)
    assert tsm.is_exhausted() is True

    tsm.record_message("user", "Hello World")
    tsm.record_token_usage(50, 100)
    snap = tsm.snapshot()
    assert snap["total_input_tokens"] == 50
    assert snap["total_output_tokens"] == 100

    tsm2 = TurnStateManager(max_turns=10)
    tsm2.restore({"current_turn": 5, "history": [{"role": "user", "content": "Restored"}]})
    assert tsm2.current_turn == 5
    assert len(tsm2.message_history) == 1
    assert tsm2.message_history[0]["content"] == "Restored"
