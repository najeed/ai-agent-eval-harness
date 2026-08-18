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

import eval_runner.hitl.pending as hitl_pending
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

    # 2. Default fallback branch (no sandbox, no handler)
    res2 = coord.execute("default_action", {"param_x": 1})
    assert res2 == {"status": "success", "result": "Executed default_action"}
    assert len(coord.executed_tools) == 2
    assert coord.executed_tools[1]["status"] == "success"

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


def test_session_approval_manager_full():
    registry = hitl_pending.PendingApprovalRegistry()
    appr_mgr = SessionApprovalManager(run_id="run_decomp_01", registry=registry)

    # Request approval
    req1 = appr_mgr.request_approval(
        "task_01", "delete_account", {"user_id": "u123"}, timeout_seconds=45
    )
    assert req1.run_id == "run_decomp_01"
    assert req1.task_id == "task_01"
    assert "delete_account" in req1.prompt

    # Request approval for a different run in same registry
    appr_mgr2 = SessionApprovalManager(run_id="run_other_02", registry=registry)
    req2 = appr_mgr2.request_approval("task_02", "restart_node", {"node_id": "n1"})

    # Test list_pending_approvals filters by run_id
    pending_01 = appr_mgr.list_pending_approvals()
    assert len(pending_01) == 1
    assert pending_01[0].id == req1.id

    pending_02 = appr_mgr2.list_pending_approvals()
    assert len(pending_02) == 1
    assert pending_02[0].id == req2.id

    # Resolve approval with custom response and resolved_by
    resolved = appr_mgr.resolve_approval(
        req1.id, "approve", response="Approved by audit", resolved_by="auditor_1"
    )
    assert resolved is True

    # Resolve approval with defaults (response=None, resolved_by=None)
    resolved2 = appr_mgr2.resolve_approval(req2.id, "reject")
    assert resolved2 is True

    # Default constructor registry initialization
    default_appr = SessionApprovalManager(run_id="run_default_reg")
    assert default_appr.registry is hitl_pending.global_registry
