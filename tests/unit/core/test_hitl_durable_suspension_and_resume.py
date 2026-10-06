"""
tests/unit/core/test_hitl_durable_suspension_and_resume.py
Acceptance and unit tests for P0 Runtime Control Plane Defects:
- P0-1: Durable HITL suspension signal (RunSuspendedForApproval, PAUSED_FOR_APPROVAL).
- P0-2: Same-run resume without vault collision, preserving manifests, monotonic trace.
- P0-3 & P0-4: Durable ApprovalRequest ingestion, cold resumption bridge.
- P0-5: Scenario-declared HITL governance gate (interaction_mode: Manual_Approval).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner import config
from eval_runner.context import TurnContext
from eval_runner.events import CoreEvents, Event
from eval_runner.exceptions import RunSuspendedForApproval
from eval_runner.execution_ir import NodeIR
from eval_runner.flight_recorder import FlightRecorderPlugin as FlightRecorder
from eval_runner.handlers.evaluation import handle_run
from eval_runner.reference.approval_store import (
    FileApprovalStore,
    reset_default_approval_store,
)
from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore
from eval_runner.run_lifecycle import (
    RunLifecycleState,
    TraceClosedError,
    assert_can_write_trace,
    can_write_trace,
    get_run_lifecycle_state,
    rollback_run_lifecycle_to_open,
    transition_run_lifecycle,
)
from eval_runner.runner import DefaultRunner, run_scenario
from eval_runner.session import SessionManager
from eval_runner.session_components import SessionCheckpointManager


@pytest.fixture(autouse=True)
def clean_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_default_approval_store()
    test_root = tmp_path / ".agentv"
    monkeypatch.setenv("AGENTV_CONFIG_DIR", str(test_root))
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    yield


# ---------------------------------------------------------------------------
# P0-1: Exception Contract & Lifecycle State Machine
# ---------------------------------------------------------------------------


def test_run_suspended_for_approval_exception_contract():
    exc = RunSuspendedForApproval(
        run_id="run-suspend-001",
        task_id="task_transfer",
        approval_token="tok-appr-abc-123",
        turn_index=2,
        checkpoint_id="chk-002",
        prompt="Authorize transfer of $5000",
        checkpoint={"state": "active"},
        action_payload={"amount": 5000},
    )

    assert isinstance(exc, InterruptedError)
    assert exc.run_id == "run-suspend-001"
    assert exc.task_id == "task_transfer"
    assert exc.approval_token == "tok-appr-abc-123"
    assert exc.turn_index == 2
    assert exc.checkpoint_id == "chk-002"
    assert exc.prompt == "Authorize transfer of $5000"
    assert exc.checkpoint == {"state": "active"}
    assert exc.action_payload == {"amount": 5000}
    assert "run-suspend-001" in str(exc)
    assert "tok-appr-abc-123" in str(exc)


def test_lifecycle_paused_for_approval_state_transitions(tmp_path: Path):
    run_id = "run-lifecycle-001"
    runs_dir = tmp_path / "runs"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)

    # 1. Start OPEN
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)
    assert get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.OPEN
    allowed, _ = can_write_trace(run_id, log_dir=runs_dir)
    assert allowed is True

    # 2. Transition OPEN -> PAUSED_FOR_APPROVAL
    transition_run_lifecycle(run_id, RunLifecycleState.PAUSED_FOR_APPROVAL, log_dir=runs_dir)
    assert (
        get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.PAUSED_FOR_APPROVAL
    )
    allowed, reason = can_write_trace(run_id, log_dir=runs_dir)
    assert allowed is False
    assert "PAUSED_FOR_APPROVAL" in reason

    # 3. Transition PAUSED_FOR_APPROVAL -> OPEN (Resumption)
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)
    assert get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.OPEN
    allowed, _ = can_write_trace(run_id, log_dir=runs_dir)
    assert allowed is True

    # 4. Finalizing and Sealed
    transition_run_lifecycle(run_id, RunLifecycleState.FINALIZING, log_dir=runs_dir)
    assert get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.FINALIZING
    transition_run_lifecycle(run_id, RunLifecycleState.SEALED, log_dir=runs_dir)
    assert get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.SEALED


@pytest.mark.asyncio
async def test_p0_1_session_durable_suspension_emits_and_preserves_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AGENTV_CLI_HITL_SUSPEND", "1")
    run_id = "run-p0-1-session"
    runs_dir = tmp_path / "runs"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)

    scenario = {
        "id": "scen_hitl",
        "metadata": {"org_id": "org_enterprise_1"},
        "workflow": [
            {
                "id": "task_1",
                "name": "Transfer Task",
                "tool": "transfer",
                "success_criteria": [{"type": "string_match", "value": "Done"}],
            }
        ],
    }

    session = SessionManager(run_id=run_id, scenario=scenario, log_root=runs_dir)
    session.resumption_token = None

    emitted_events = []
    session.event_bus.subscribe(
        lambda ev: (
            emitted_events.append(ev.data)
            if ev.name == CoreEvents.HITL_PAUSE and ev.data.get("status") == "PAUSED_FOR_APPROVAL"
            else None
        )
    )

    turn_ctx = TurnContext(task_id="task_1", turn_number=1, current_message="message", history=())

    with pytest.raises(RunSuspendedForApproval) as exc_info:
        await session._handle_hitl(
            turn=1,
            agent_response={
                "action": "hitl_pause",
                "prompt": "Admin signature required for wire transfer",
                "required_role": "compliance_officer",
            },
            history=[],
            actions={},
            turn_ctx=turn_ctx,
        )

    err = exc_info.value
    assert err.run_id == run_id
    assert err.task_id == "task_1"
    assert err.prompt == "Admin signature required for wire transfer"
    assert len(emitted_events) == 1
    assert emitted_events[0]["status"] == "PAUSED_FOR_APPROVAL"
    assert (
        get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.PAUSED_FOR_APPROVAL
    )


# ---------------------------------------------------------------------------
# P0-2: Same-Run Resume Evidence Vault & Canonical Trace Appending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0_2_flight_recorder_monotonic_resumption_sequence(tmp_path: Path):
    run_id = "run-fr-monotonic"
    runs_root = tmp_path / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    log_dir = runs_root / run_id

    recorder = FlightRecorder(log_dir=runs_root)

    # Initial session writes RUN_START and 2 steps
    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": run_id, "scenario": "scen_1"}))
    recorder.handle_event(Event(CoreEvents.STEP_START, {"run_id": run_id, "step": 1}))
    recorder.handle_event(Event(CoreEvents.STEP_END, {"run_id": run_id, "step": 1}))

    trace_file = log_dir / "run.jsonl"
    assert trace_file.exists()
    lines_pre_pause = [json.loads(line) for line in trace_file.read_text().splitlines() if line]
    assert len(lines_pre_pause) == 3
    pre_seqs = [item["_seq"] for item in lines_pre_pause]
    assert pre_seqs == [1, 2, 3]

    # Process stops (simulate pause), recorder instance is recreated
    del recorder
    recorder_resumed = FlightRecorder(log_dir=runs_root)

    # Resume session with is_resume=True
    recorder_resumed.handle_event(
        Event(
            CoreEvents.RUN_START,
            {"run_id": run_id, "scenario": "scen_1", "is_resume": True},
        )
    )
    recorder_resumed.handle_event(Event(CoreEvents.STEP_START, {"run_id": run_id, "step": 2}))
    recorder_resumed.handle_event(
        Event(CoreEvents.RUN_END, {"run_id": run_id, "status": "COMPLETED"})
    )

    lines_post_resume = [json.loads(line) for line in trace_file.read_text().splitlines() if line]
    all_seqs = [item["_seq"] for item in lines_post_resume]

    # Monotonicity check: strictly increasing without reset or gaps
    assert all_seqs == [1, 2, 3, 4, 5, 6]
    event_names = [item.get("event") for item in lines_post_resume]
    assert event_names == [
        CoreEvents.RUN_START,
        CoreEvents.STEP_START,
        CoreEvents.STEP_END,
        CoreEvents.RUN_START,
        CoreEvents.STEP_START,
        CoreEvents.RUN_END,
    ]


@pytest.mark.asyncio
async def test_p0_2_runner_resumption_preserves_manifest_and_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    run_id = "run-runner-resume-001"
    runs_dir = tmp_path / "runs"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)

    manifest_data = {
        "manifest_version": "1.0.0",
        "run_id": run_id,
        "scenario_digest": "sha256:abc123canonical",
    }
    manifest_path = vault_dir / "execution_manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    scenario = {
        "id": "scen_resume_test",
        "metadata": {"org_id": "org_test"},
        "workflow": [
            {
                "id": "node_1",
                "name": "Task 1",
                "tool": "noop",
                "success_criteria": [{"type": "string_match", "value": "Done"}],
            },
        ],
    }

    # Pre-set lifecycle OPEN then PAUSED_FOR_APPROVAL
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)
    transition_run_lifecycle(run_id, RunLifecycleState.PAUSED_FOR_APPROVAL, log_dir=runs_dir)

    # Setup approval store with approved request
    approval_store = FileApprovalStore(base_dir=tmp_path / ".agentv" / "approvals")
    token = "tok-resume-123"
    approval_store.create_request(
        ApprovalRequest(
            approval_token=token,
            run_id=run_id,
            turn_index=1,
            outbound_payload_hash="sha256:mock",
            status="APPROVED",
            metadata={"task_id": "node_1", "org_id": "org_test"},
        )
    )

    runner = DefaultRunner()

    patch_store = patch(
        "eval_runner.reference.approval_store.get_default_approval_store",
        return_value=approval_store,
    )
    patch_agent = patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        AsyncMock(return_value={"action": "final_answer", "content": "Done"}),
    )

    with patch_store, patch_agent:
        result = await runner.run(
            scenario=scenario,
            run_id=run_id,
            resumption_token=token,
        )

    assert result is not None
    # Verify manifest was preserved
    assert manifest_path.exists()
    assert json.loads(manifest_path.read_text()) == manifest_data
    # Verify lifecycle is reopened during execution
    assert get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.OPEN
    # Explicit plugin finalization transitions to FINALIZING/SEALED
    FlightRecorder(log_dir=runs_dir).finalize_run(run_id)
    assert get_run_lifecycle_state(run_id, log_dir=runs_dir) in (
        RunLifecycleState.FINALIZING,
        RunLifecycleState.SEALED,
    )


def test_p0_2_runner_fresh_run_rejects_existing_vault(tmp_path: Path):
    run_id = "run-existing-vault"
    vault_dir = tmp_path / "runs" / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)

    scenario = {"id": "scen_existing", "workflow": []}
    runner = DefaultRunner()

    with pytest.raises(RuntimeError, match="RunIdCollision: evidence vault already exists"):
        run_scenario(
            scenario=scenario,
            runner=runner,
            run_id=run_id,
        )


def test_p0_2_runner_resumption_fails_closed_on_terminal_state(tmp_path: Path):
    run_id = "run-sealed-resume"
    runs_dir = tmp_path / "runs"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)
    transition_run_lifecycle(run_id, RunLifecycleState.FINALIZING, log_dir=runs_dir)
    transition_run_lifecycle(run_id, RunLifecycleState.SEALED, log_dir=runs_dir)

    scenario = {"id": "scen_sealed", "workflow": []}
    runner = DefaultRunner()

    with pytest.raises(
        RuntimeError,
        match="ResumptionError: cannot resume run 'run-sealed-resume' in terminal lifecycle state",
    ):
        run_scenario(
            scenario=scenario,
            runner=runner,
            run_id=run_id,
            resumption_token="tok-xyz",
        )


# ---------------------------------------------------------------------------
# P0-3 & P0-4: Durable ApprovalRequest Ingestion & Cold Resumption Bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p0_3_and_p0_4_cold_restart_hitl_bridge(tmp_path: Path):
    run_id = "run-cold-bridge-001"
    token = "tok-cold-999"
    db_path = str(tmp_path / "checkpoints.db")
    chk_store = SQLiteCheckpointStore(db_path=db_path)
    approval_store = FileApprovalStore(base_dir=tmp_path / "approvals")

    scenario = {
        "id": "scen_bridge",
        "metadata": {"org_id": "org_corp_fin"},
        "workflow": [
            {
                "id": "step_1",
                "tool": "authorize_disbursement",
                "params": {"amount": 50000},
                "success_criteria": [{"type": "string_match", "value": "Disbursed"}],
            }
        ],
    }

    # Persist durable checkpoint and approval request
    chk_store.save(
        run_id,
        "checkpoint_turn_1",
        {
            "run_id": run_id,
            "status": "PAUSED_FOR_APPROVAL",
            "resumption_token": token,
            "scenario_data": scenario,
            "turn_number": 1,
            "session_state": {
                "status": "PAUSED_FOR_APPROVAL",
                "approval_token": token,
                "completed_node_results": {},
            },
        },
    )

    approval_store.create_request(
        ApprovalRequest(
            approval_token=token,
            run_id=run_id,
            turn_index=1,
            outbound_payload_hash="sha256:fedcba",
            checkpoint_id="checkpoint_turn_1",
            status="APPROVED",
            metadata={"org_id": "org_corp_fin", "task_id": "step_1"},
        )
    )

    # Initialize a cold backend with zero in-memory state
    backend = InProcessExecutionBackend(checkpoint_store=chk_store)
    assert run_id not in backend._active_runs

    status = backend.status(run_id)
    assert status["status"] == "PAUSED_FOR_APPROVAL"

    patch_store = patch(
        "eval_runner.reference.approval_store.get_default_approval_store",
        return_value=approval_store,
    )
    patch_agent = patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        AsyncMock(return_value={"action": "final_answer", "content": "Disbursed"}),
    )

    with patch_store, patch_agent:
        result = backend.resume(run_id=run_id, resumption_token=token, background=False)

    assert result is not None
    assert backend.status(run_id)["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# P0-5: Scenario-Declared HITL Governance Gate
# ---------------------------------------------------------------------------


def test_p0_5_node_ir_compilation_detects_manual_approval():
    raw_node_1 = {
        "id": "node_audit",
        "name": "Audit Transfer",
        "interaction_mode": "Manual_Approval",
    }
    node_ir_1 = NodeIR(node_id="node_audit", definition=raw_node_1)
    assert node_ir_1.has_hitl_gate is True
    assert node_ir_1.hitl_gate_timing == "before"

    raw_node_2 = {
        "id": "node_post_check",
        "hitl_gate": {"timing": "after", "role": "compliance"},
    }
    node_ir_2 = NodeIR(node_id="node_post_check", definition=raw_node_2)
    assert node_ir_2.has_hitl_gate is True
    assert node_ir_2.hitl_gate_timing == "after"

    raw_node_3 = {
        "id": "node_standard",
        "tool": "noop",
    }
    node_ir_3 = NodeIR(node_id="node_standard", definition=raw_node_3)
    assert node_ir_3.has_hitl_gate is False


@pytest.mark.asyncio
async def test_p0_5_session_enforces_scenario_declared_manual_approval_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AGENTV_CLI_HITL_SUSPEND", "1")
    run_id = "run-p0-5-gate"
    runs_dir = tmp_path / "runs"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)

    scenario = {
        "id": "scen_gate_test",
        "metadata": {"org_id": "org_regulatory"},
        "workflow": [
            {
                "id": "wire_transfer",
                "name": "Execute High Value Wire",
                "interaction_mode": "Manual_Approval",
                "tool": "wire",
                "success_criteria": [{"type": "string_match", "value": "Done"}],
            }
        ],
    }

    session = SessionManager(run_id=run_id, scenario=scenario, log_root=runs_dir)

    # Node has interaction_mode: Manual_Approval
    node = scenario["workflow"][0]
    assert session._should_enforce_hitl_gate(node, timing="before") is True

    # Execution of tasks must suspend before the agent completes
    with pytest.raises(RunSuspendedForApproval) as exc_info:
        await session.execute_tasks(attempt_number=1)

    err = exc_info.value
    assert err.run_id == run_id
    assert err.task_id == "wire_transfer"
    assert "Manual approval required" in err.prompt


def test_p0_session_checkpoint_manager_loading_and_listing(tmp_path: Path):
    db_file = str(tmp_path / "chk.db")
    store = SQLiteCheckpointStore(db_path=db_file)
    mgr = SessionCheckpointManager(run_id="run-mgr-chk", store=store)

    uri_1 = mgr.create_checkpoint({"step": 1}, metadata={"turn": 1})
    _ = mgr.create_checkpoint({"step": 2}, metadata={"turn": 2})

    latest = mgr.load_latest_checkpoint()
    assert latest is not None
    assert latest["step"] == 2

    # Load by direct ID
    first_by_id = mgr.load_checkpoint("chk_0001")
    assert first_by_id is not None
    assert first_by_id["step"] == 1

    # Load by URI
    first_by_uri = mgr.load_checkpoint(uri_1)
    assert first_by_uri is not None
    assert first_by_uri["step"] == 1

    # Load by non-string checkpoint identifier
    assert mgr.load_checkpoint(99999) is None

    checkpoints = mgr.list_checkpoints()
    assert len(checkpoints) == 2

    # Verify default store instantiation
    default_mgr = SessionCheckpointManager(run_id="run-default-store", store=None)
    assert default_mgr.store is not None


def test_p0_run_lifecycle_edge_branches(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Empty / unknown run_id rollback returns OPEN
    assert rollback_run_lifecycle_to_open("", log_dir=runs_dir) == RunLifecycleState.OPEN
    assert rollback_run_lifecycle_to_open("unknown", log_dir=runs_dir) == RunLifecycleState.OPEN

    # Rollback on sealed run raises ValueError
    run_id = "run-sealed-edge"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)
    transition_run_lifecycle(run_id, RunLifecycleState.FINALIZING, log_dir=runs_dir)
    transition_run_lifecycle(run_id, RunLifecycleState.SEALED, log_dir=runs_dir)

    with pytest.raises(ValueError, match="Cannot rollback lifecycle for SEALED run"):
        rollback_run_lifecycle_to_open(run_id, log_dir=runs_dir)

    # Rollback on finalizing run resets to OPEN
    run_fin = "run-fin-edge"
    vault_fin = runs_dir / run_fin
    vault_fin.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_fin, RunLifecycleState.OPEN, log_dir=runs_dir)
    transition_run_lifecycle(run_fin, RunLifecycleState.FINALIZING, log_dir=runs_dir)
    assert rollback_run_lifecycle_to_open(run_fin, log_dir=runs_dir) == RunLifecycleState.OPEN

    # Rollback when unlink raises OSError still returns OPEN
    transition_run_lifecycle(run_fin, RunLifecycleState.FINALIZING, log_dir=runs_dir)
    with patch.object(Path, "unlink", side_effect=OSError("Unlink permission error")):
        assert rollback_run_lifecycle_to_open(run_fin, log_dir=runs_dir) == RunLifecycleState.OPEN

    # transition_run_lifecycle re-raises OSError on marker write failure
    with patch.object(Path, "replace", side_effect=OSError("Write disk full")):
        with pytest.raises(OSError, match="Write disk full"):
            transition_run_lifecycle("run-disk-err", RunLifecycleState.OPEN, log_dir=runs_dir)

    # can_write_trace with UNKNOWN state returns False
    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
        return_value=RunLifecycleState.UNKNOWN,
    ):
        allowed, reason = can_write_trace("run-unknown", log_dir=runs_dir)
        assert allowed is False
        assert "UNKNOWN" in reason

    # assert_can_write_trace on PAUSED_FOR_APPROVAL raises TraceClosedError
    run_paused = "run-assert-paused"
    vault_paused = runs_dir / run_paused
    vault_paused.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_paused, RunLifecycleState.OPEN, log_dir=runs_dir)
    transition_run_lifecycle(run_paused, RunLifecycleState.PAUSED_FOR_APPROVAL, log_dir=runs_dir)
    with pytest.raises(TraceClosedError, match="PAUSED_FOR_APPROVAL"):
        assert_can_write_trace(run_paused, log_dir=runs_dir)


def test_p0_flight_recorder_resumption_failure_branches(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = "run-fr-fail-closed"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Sealed run rejection on resumption
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)
    transition_run_lifecycle(run_id, RunLifecycleState.FINALIZING, log_dir=runs_dir)
    transition_run_lifecycle(run_id, RunLifecycleState.SEALED, log_dir=runs_dir)

    recorder = FlightRecorder(log_dir=runs_dir)
    with pytest.raises(RuntimeError, match="ResumptionError"):
        recorder.handle_event(
            Event(
                CoreEvents.RUN_START,
                {"run_id": run_id, "scenario": "scen_test", "is_resume": True},
            )
        )

    # Monotonic scan resilience over corrupt trace lines
    run_corrupt = "run-fr-corrupt"
    vault_corrupt = runs_dir / run_corrupt
    vault_corrupt.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_corrupt, RunLifecycleState.OPEN, log_dir=runs_dir)
    trace_file = vault_corrupt / "run.jsonl"
    trace_file.write_text('{"_seq": 5}\n{bad_json\n{"_seq": 12}\n', encoding="utf-8")

    recorder2 = FlightRecorder(log_dir=runs_dir)
    recorder2.handle_event(
        Event(
            CoreEvents.RUN_START,
            {"run_id": run_corrupt, "scenario": "scen_test", "is_resume": True},
        )
    )
    # The next event sequence should be 13 (initialized to max parsed 12)
    recorder2.handle_event(Event(CoreEvents.STEP_START, {"run_id": run_corrupt, "step": 1}))
    lines = [json.loads(line) for line in trace_file.read_text().splitlines() if "event" in line]
    assert lines[-1]["_seq"] == 14


@pytest.mark.asyncio
async def test_p0_evaluation_handler_catches_run_suspended_for_approval(capsys):
    args = argparse.Namespace(
        scenario="scen_dummy",
        agent=None,
        k=1,
        mode=None,
        resumption_token=None,
        run_id=None,
    )
    susp_exc = RunSuspendedForApproval(
        run_id="run-cli-susp-01",
        task_id="wire",
        approval_token="tok-cli-susp-abc",
    )
    with (
        patch(
            "eval_runner.handlers.evaluation.loader.load_scenario",
            return_value=({"id": "scen_dummy"}, Path("dummy.json")),
        ),
        patch("eval_runner.handlers.evaluation.engine.run_evaluation", side_effect=susp_exc),
    ):
        rc = await handle_run(args)
        assert rc == 0

    captured = capsys.readouterr()
    assert "[HITL PAUSE]" in captured.out
    assert "tok-cli-susp-abc" in captured.out
    assert "agentv hitl-resume" in captured.out


@pytest.mark.asyncio
async def test_p0_runner_catches_suspension_and_marks_lifecycle(tmp_path: Path):
    run_id = "run-runner-susp-catch"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    scenario = {
        "id": "scen_susp",
        "workflow": [{"id": "task_1", "tool": "noop"}],
    }
    runner = DefaultRunner()

    susp_exc = RunSuspendedForApproval(
        run_id=run_id,
        task_id="task_1",
        approval_token="tok-runner-susp-001",
    )

    with patch("eval_runner.session.SessionManager.execute_tasks", side_effect=susp_exc):
        with pytest.raises(RunSuspendedForApproval) as exc_info:
            await runner.run(scenario=scenario, run_id=run_id)

    assert exc_info.value.approval_token == "tok-runner-susp-001"
    assert (
        get_run_lifecycle_state(run_id, log_dir=runs_dir) == RunLifecycleState.PAUSED_FOR_APPROVAL
    )


@pytest.mark.asyncio
async def test_p0_session_hitl_resumption_and_gate_branches(tmp_path: Path):
    run_id = "run-session-branches"
    runs_dir = tmp_path / "runs"
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    transition_run_lifecycle(run_id, RunLifecycleState.OPEN, log_dir=runs_dir)

    scenario = {
        "id": "scen_branches",
        "workflow": [
            {
                "id": "node_before",
                "interaction_mode": "Manual_Approval",
                "tool": "wire",
            },
            {
                "id": "node_after",
                "hitl_gate": {"timing": "after"},
                "tool": "wire",
            },
            {
                "id": "node_regular",
                "tool": "read",
            },
        ],
    }

    session = SessionManager(run_id=run_id, scenario=scenario, log_root=runs_dir)

    node_before = scenario["workflow"][0]
    node_after = scenario["workflow"][1]
    node_regular = scenario["workflow"][2]

    # Gate timing checks
    assert session._should_enforce_hitl_gate(node_before, timing="before") is True
    assert session._should_enforce_hitl_gate(node_before, timing="after") is False
    assert session._should_enforce_hitl_gate(node_after, timing="before") is False
    assert session._should_enforce_hitl_gate(node_after, timing="after") is True
    assert session._should_enforce_hitl_gate(node_regular, timing="before") is False

    # Mark pre-approved gate
    session._mark_gate_approved("node_before")
    assert session._should_enforce_hitl_gate(node_before, timing="before") is False

    # Resumption token with approved request
    approval_store = FileApprovalStore(base_dir=tmp_path / ".agentv" / "approvals")
    token = "tok-branch-appr"
    approval_store.create_request(
        ApprovalRequest(
            approval_token=token,
            run_id=run_id,
            turn_index=1,
            outbound_payload_hash="sha256:abc",
            status="APPROVED",
            decision_reason="Authorized by compliance officer",
            metadata={"task_id": "node_after"},
        )
    )

    session.resumption_token = token
    with patch(
        "eval_runner.reference.approval_store.get_default_approval_store",
        return_value=approval_store,
    ):
        # Gate pre-approval via resumption token
        assert session._should_enforce_hitl_gate(node_after, timing="after") is False

        # _handle_hitl resolves immediately via resumption token
        res = await session._handle_hitl(
            turn=1,
            agent_response={"action": "hitl_pause"},
            history=[],
            actions={},
            turn_ctx=TurnContext(
                task_id="node_after",
                turn_number=1,
                current_message="req",
                history=(),
            ),
        )
        assert res == "Authorized by compliance officer"
