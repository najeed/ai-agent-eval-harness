"""
tests/unit/test_session_decomposition.py
Validation for Decomposed Session Subsystems.
"""

from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore
from eval_runner.session_components import (
    SessionApprovalManager,
    SessionCheckpointManager,
    ToolExecutionCoordinator,
    TurnStateManager,
)


def test_turn_state_manager():
    mgr = TurnStateManager(max_turns=3)
    assert mgr.current_turn == 0
    assert mgr.is_exhausted() is False

    mgr.start_turn()
    assert mgr.current_turn == 1

    mgr.record_message("user", "Hello agent")
    mgr.record_token_usage(100, 50)
    assert mgr.total_input_tokens == 100
    assert mgr.total_output_tokens == 50

    snap = mgr.snapshot()
    assert snap["current_turn"] == 1
    assert snap["message_count"] == 1

    # Max turns
    mgr.start_turn()
    mgr.start_turn()
    assert mgr.is_exhausted() is True


def test_tool_execution_coordinator():
    coord = ToolExecutionCoordinator()
    assert len(coord.executed_tools) == 0

    def mock_tool(amount: int):
        return {"processed": amount}

    res = coord.execute("payment_api", {"amount": 500}, handler=mock_tool)
    assert res == {"processed": 500}
    assert len(coord.executed_tools) == 1
    assert coord.executed_tools[0]["status"] == "success"

    snap = coord.snapshot()
    assert snap["executed_count"] == 1
    assert "payment_api" in snap["tool_names"]


def test_session_checkpoint_and_approval_managers(tmp_path):
    db_file = str(tmp_path / "test_sess_chk.db")
    chk_store = SQLiteCheckpointStore(db_path=db_file)
    chk_mgr = SessionCheckpointManager(run_id="run_decomp_01", store=chk_store)

    uri = chk_mgr.create_checkpoint({"turn": 2, "state": "active"})
    assert "sqlite://" in uri
    assert len(chk_mgr.list_checkpoints()) == 1
    assert chk_mgr.load_latest_checkpoint() == {"turn": 2, "state": "active"}

    appr_mgr = SessionApprovalManager(run_id="run_decomp_01")
    req = appr_mgr.request_approval("task_01", "delete_account", {"user_id": "u123"})
    assert req.run_id == "run_decomp_01"
    assert req.task_id == "task_01"
    assert "delete_account" in req.prompt

    # Resolve
    resolved = appr_mgr.resolve_approval(req.id, "approve", response="Allowed by admin")
    assert resolved is True
