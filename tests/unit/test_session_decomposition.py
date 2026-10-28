"""
tests/unit/test_session_decomposition.py
Comprehensive 100% Unit Test Coverage for Decomposed Session Subsystems:
- TurnStateManager
- ToolExecutionCoordinator
- SessionCheckpointManager
- SessionApprovalManager
"""

from unittest.mock import MagicMock

import pytest

from eval_runner.reference.approval_store import FileApprovalStore
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore
from eval_runner.session_components import (
    SessionApprovalManager,
    SessionCheckpointManager,
    ToolExecutionCoordinator,
    TurnStateManager,
)


def test_turn_state_manager_full_lifecycle():
    mgr = TurnStateManager(max_turns=3)
    assert mgr.current_turn == 0
    assert mgr.is_exhausted() is False

    # Default turn increment
    t1 = mgr.start_turn()
    assert t1 == 1
    assert mgr.current_turn == 1

    # Explicit turn setting
    t5 = mgr.start_turn(turn_number=5)
    assert t5 == 5
    assert mgr.current_turn == 5

    # Messages with and without metadata
    mgr.record_message("user", "Hello agent")
    mgr.record_message("assistant", "I am ready", metadata={"confidence": 0.99})
    assert len(mgr.message_history) == 2
    assert mgr.message_history[0]["metadata"] == {}
    assert mgr.message_history[1]["metadata"]["confidence"] == 0.99

    # Token usage accumulation (including negative clamp)
    mgr.record_token_usage(100, 50)
    mgr.record_token_usage(-10, -20)
    assert mgr.total_input_tokens == 100
    assert mgr.total_output_tokens == 50

    # Snapshot
    snap = mgr.snapshot()
    assert snap["current_turn"] == 5
    assert snap["max_turns"] == 3
    assert snap["total_input_tokens"] == 100
    assert snap["total_output_tokens"] == 50
    assert snap["message_count"] == 2

    # Exhaustion
    assert mgr.is_exhausted() is True

    # Restore from state
    mgr.restore(
        {
            "current_turn": 2,
            "max_turns": 10,
            "total_input_tokens": 500,
            "total_output_tokens": 250,
        }
    )
    assert mgr.current_turn == 2
    assert mgr.max_turns == 10
    assert mgr.total_input_tokens == 500
    assert mgr.total_output_tokens == 250
    assert mgr.is_exhausted() is False

    # Restore with empty state defaults
    mgr.restore({})
    assert mgr.current_turn == 0
    assert mgr.total_input_tokens == 0
    assert mgr.total_output_tokens == 0


def test_tool_execution_coordinator_branches():
    # 1. Custom handler branch
    coord = ToolExecutionCoordinator()
    assert len(coord.executed_tools) == 0

    def mock_tool(amount: int):
        return {"processed": amount}

    res1 = coord.execute("payment_api", {"amount": 500}, handler=mock_tool)
    assert res1 == {"processed": 500}
    assert len(coord.executed_tools) == 1
    assert coord.executed_tools[0]["status"] == "success"

    # 2. An unbound tool is a typed, fail-closed execution failure.
    with pytest.raises(RuntimeError, match="ToolUnavailable"):
        coord.execute("default_action", {"param_x": 1})
    assert len(coord.executed_tools) == 2
    assert coord.executed_tools[1]["status"] == "error"

    # 3. Sandbox execution branch
    mock_sandbox = MagicMock()
    mock_sandbox.execute_tool.return_value = {"sandbox_result": "ok"}
    coord_sandboxed = ToolExecutionCoordinator(sandbox=mock_sandbox)
    res3 = coord_sandboxed.execute("sandboxed_tool", {"arg": "value"})
    assert res3 == {"sandbox_result": "ok"}
    mock_sandbox.execute_tool.assert_called_once_with("sandboxed_tool", {"arg": "value"})
    assert coord_sandboxed.executed_tools[0]["status"] == "success"

    # 4. Exception branch
    def failing_tool(**kwargs):
        raise ValueError("Invalid parameters")

    with pytest.raises(ValueError, match="Invalid parameters"):
        coord.execute("fail_tool", {"bad": True}, handler=failing_tool)

    assert len(coord.executed_tools) == 3
    assert coord.executed_tools[2]["status"] == "error"
    assert "Invalid parameters" in coord.executed_tools[2]["error"]

    # 5. Snapshot
    snap = coord.snapshot()
    assert snap["executed_count"] == 3
    assert snap["tool_names"] == ["payment_api", "default_action", "fail_tool"]


def test_session_checkpoint_manager_full(tmp_path):
    db_file = str(tmp_path / "test_sess_chk.db")
    chk_store = SQLiteCheckpointStore(db_path=db_file)
    chk_mgr = SessionCheckpointManager(run_id="run_decomp_01", store=chk_store)

    assert chk_mgr.store is chk_store

    # Auto-incrementing checkpoint id
    uri1 = chk_mgr.create_checkpoint({"turn": 1, "state": "start"})
    assert "sqlite://" in uri1

    # Explicit checkpoint id & metadata
    uri2 = chk_mgr.create_checkpoint(
        {"turn": 2, "state": "active"},
        checkpoint_id="chk_custom_02",
        metadata={"author": "test"},
    )
    assert "sqlite://" in uri2

    checkpoints = chk_mgr.list_checkpoints()
    assert len(checkpoints) == 2

    latest = chk_mgr.load_latest_checkpoint()
    assert latest["turn"] == 2
    assert latest["state"] == "active"

    # Default store initialization when store is None
    default_mgr = SessionCheckpointManager(run_id="run_default_store")
    assert default_mgr.store is not None
    assert isinstance(default_mgr.store, SQLiteCheckpointStore)


def test_session_approval_manager_full(tmp_path):
    store = FileApprovalStore(tmp_path / "approvals")
    runs = LocalFileRunStore(tmp_path / "runs")
    context = {"tenant_id": "test", "workspace_id": "test", "active_environment": "test"}
    runs.create_run("run_decomp_01", "scenario", context=context)
    runs.create_run("run_other_02", "scenario", context=context)
    appr_mgr = SessionApprovalManager(run_id="run_decomp_01", approval_store=store, run_store=runs)

    # Request approval
    req1 = appr_mgr.create_durable_request(
        1,
        metadata={"task_id": "task_01", "runtime_context": context},
        action_payload={"user_id": "u123"},
        prompt="delete_account",
    )
    assert req1.run_id == "run_decomp_01"
    assert req1.metadata["task_id"] == "task_01"
    assert "delete_account" in req1.prompt

    # Request approval for a different run in same registry
    appr_mgr2 = SessionApprovalManager(run_id="run_other_02", approval_store=store, run_store=runs)
    req2 = appr_mgr2.create_durable_request(
        1,
        metadata={"task_id": "task_02", "runtime_context": context},
        action_payload={"node_id": "n1"},
        prompt="restart_node",
    )

    # Test list_pending_approvals filters by run_id
    pending_01 = store.list_pending(run_id="run_decomp_01")
    assert len(pending_01) == 1
    assert pending_01[0].approval_token == req1.approval_token

    pending_02 = store.list_pending(run_id="run_other_02")
    assert len(pending_02) == 1
    assert pending_02[0].approval_token == req2.approval_token

    # Resolve approval with custom response and resolved_by
    resolved = appr_mgr.resolve_durable_request(
        req1.approval_token, "APPROVED", "auditor_1", "Approved by audit"
    )
    assert resolved.status == "APPROVED"

    # Resolve approval with defaults (response=None, resolved_by=None)
    resolved2 = appr_mgr2.resolve_durable_request(req2.approval_token, "REJECTED")
    assert resolved2.status == "REJECTED"
