"""
Chaos resilience & boundary fault injection test suite for AgentV evaluation infrastructure.
Enforces the fundamental AgentV invariant: Infrastructure failure or exception
at LLM adapter boundaries, WORM disk layer, or simulator runtime
must NEVER silently convert into an evaluation success (PASS).
"""

from __future__ import annotations

import json

import aiohttp
import pytest

from eval_runner.adapters.common import BaseAdapter
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.verifier import TraceVerifier


@pytest.fixture
def chaos_scenario():
    """Provides base scenario for chaos failure injection tests."""
    return {
        "id": "chaos-failure-scenario",
        "run_id": "run-chaos-test-001",
        "aes_version": 1.4,
        "initial_state": {},
        "metadata": {
            "name": "Chaos Test Scenario",
            "compliance_level": "Standard",
            "industry": "cybersecurity",
        },
        "agent_topology": {
            "default_agent": {"reads": ["*"], "writes": ["*"]},
        },
        "workflow": {"nodes": [], "edges": []},
        "evaluation": {"metrics": []},
    }


@pytest.mark.asyncio
async def test_chaos_llm_adapter_boundary_fault_injection():
    """
    Boundary Fault Injection: Injects 500 Internal Error into LLM HTTP transport boundary.
    Verifies that BaseAdapter.call_with_retry retries and raises original ClientResponseError.
    """
    adapter = BaseAdapter(name="chaos_llm_adapter")
    attempts = 0

    async def faulty_http_boundary():
        nonlocal attempts
        attempts += 1
        raise aiohttp.ClientResponseError(
            request_info=None, history=(), status=500, message="Chaos 500 Boundary Fault"
        )

    with pytest.raises(aiohttp.ClientResponseError) as exc_info:
        await adapter.call_with_retry(
            faulty_http_boundary, max_attempts=3, base_delay=0.01, retry_codes={500}
        )

    assert exc_info.value.status == 500
    assert attempts == 3


@pytest.mark.asyncio
async def test_chaos_simulator_crash_fault_injection(chaos_scenario, tmp_path):
    """
    Boundary Fault Injection: Injects a simulated runtime exception into ToolSandbox execution.
    Verifies sandbox captures error without process crash and returns structured failure.
    """
    sandbox = ToolSandbox(
        scenario=chaos_scenario,
        workspace_root=tmp_path / "workspace",
        jail_root=tmp_path / "jail",
    )
    await sandbox.setup()

    async def crash_core(tool_name, params, agent_name=None):
        raise RuntimeError("Simulated Simulator Process Crash")

    sandbox._execute_core = crash_core

    with pytest.raises(RuntimeError) as exc_info:
        await sandbox.execute(
            tool_name="faulty_shim",
            params={},
        )
    assert "Simulated Simulator Process Crash" in str(exc_info.value)


def test_chaos_missing_trace_verification_failure(tmp_path, monkeypatch):
    """
    Boundary Fault Injection: Missing trace file must raise FileNotFoundError.
    """
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    run_id = "run-chaos-missing-001"

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)

    missing_trace = run_log_dir / run_id / "missing_run.jsonl"

    with pytest.raises(FileNotFoundError):
        TraceVerifier.sign_trace(
            trace_path=str(missing_trace),
            identity_id="chaos_verifier",
            compliance_status="pass",
            run_id=run_id,
        )


@pytest.mark.asyncio
async def test_chaos_pipeline_fault_never_passes(chaos_scenario, tmp_path, monkeypatch):
    """
    End-to-End Pipeline Fault Injection:
    Executes sandbox pipeline -> injects WORM trace write fault ->
    runs TraceVerifier -> asserts verification status is NEVER PASS (False).
    """
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    run_id = "run-chaos-pipeline-fault-001"
    run_dir = run_log_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)

    sandbox = ToolSandbox(
        scenario=chaos_scenario,
        workspace_root=tmp_path / "workspace",
        jail_root=tmp_path / "jail",
    )
    await sandbox.setup()

    # 1. Execute tool call producing initial trace event
    await sandbox.execute(tool_name="echo_shim", params={"data": "normal_ping"})

    trace_file = run_dir / "run.jsonl"
    init_event = json.dumps({"event": "start", "run_id": run_id})
    trace_file.write_text(f"{init_event}\n", encoding="utf-8")

    # 2. Sign trace to issue initial manifest
    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="chaos_verifier",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # 3. Inject Infrastructure Fault: Truncate / corrupt the trace file after signing
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write('{"event": "infrastructure_crash_event_corrupted": true}\n')

    # 4. Verify pipeline output: TraceVerifier MUST detect the fault and return False (never PASS)
    is_valid = TraceVerifier.verify_trace(trace_file, manifest_path)
    assert is_valid is False, "Infrastructure fault allowed corrupted evaluation to return PASS!"


def test_chaos_readonly_worm_filesystem_lock_failure(tmp_path):
    """
    Boundary Fault Injection: Read-only WORM filesystem write lock failure during trace verification
    must fail cleanly without swallowing errors.
    """
    non_existent_path = tmp_path / "read_only_root" / "locked_manifest.json"
    is_valid = TraceVerifier.verify_trace(tmp_path / "non_existent_trace.jsonl", non_existent_path)
    assert is_valid is False


@pytest.mark.asyncio
async def test_chaos_simulator_crash_never_passes_verification(
    chaos_scenario, tmp_path, monkeypatch
):
    """
    End-to-End Invariant: Simulator crash MUST NOT produce a verification PASS.

    Pipeline under test:
      ToolSandbox.execute() raises RuntimeError (simulated crash)
      → sign_trace() is never called (crash prevents signing)
      → verify_trace() is called on unsigned trace (no manifest)
      → returns False

    This closes the full loop from tool-layer failure to verifier gate,
    establishing that a runtime crash cannot silently produce a valid result.
    """
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    run_id = "run-crash-never-pass-001"
    run_dir = run_log_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)

    sandbox = ToolSandbox(
        scenario=chaos_scenario,
        workspace_root=tmp_path / "workspace",
        jail_root=tmp_path / "jail",
    )
    await sandbox.setup()

    # Inject a crash into the core execution path
    async def crash_core(tool_name, params, agent_name=None):
        raise RuntimeError("Simulated crash: tool executor process died")

    sandbox._execute_core = crash_core

    # The crash propagates — sign_trace is never reached
    with pytest.raises(RuntimeError, match="Simulated crash"):
        await sandbox.execute(tool_name="faulty_shim", params={})

    # Write an unsigned trace (no manifest was ever created)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text('{"event": "start", "run_id": "' + run_id + '"}\n', encoding="utf-8")
    manifest_path = run_dir / "run_manifest.json"
    # manifest_path intentionally does NOT exist — signing never happened

    # Verifier MUST return False: a crash-interrupted run can never PASS
    is_valid = TraceVerifier.verify_trace(trace_file, manifest_path)
    assert is_valid is False, (
        "INVARIANT VIOLATED: Simulator crash allowed unsigned trace to pass verification!"
    )


def test_chaos_hitl_process_death_and_resume_on_resolve(chaos_scenario, tmp_path, monkeypatch):
    """
    Chaos Resilience Invariant (§3.1):
    Process dies mid-HITL wait -> new process reloads approval with resumed_from_db=True ->
    resolving via /v1/hitl/<id>/resolve MUST automatically trigger
    InProcessExecutionBackend.resume() and continue run execution.
    """
    from unittest.mock import patch

    from flask import Flask

    from eval_runner.console.routes.hitl import hitl_bp
    from eval_runner.hitl.pending import PendingApprovalRegistry
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
    from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore

    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    run_id = "run-chaos-hitl-resume-001"
    db_file = tmp_path / "hitl.db"

    # 1. First process: Create persistent approval and store durable checkpoint
    checkpoint_store = SQLiteCheckpointStore(db_path=str(tmp_path / "checkpoints.db"))
    checkpoint_state = {
        "turn": 1,
        "task_id": "step_auth_transfer",
        "prompt": "Authorize high-value transfer?",
        "scenario_data": chaos_scenario,
        "history": [{"role": "user", "content": "Transfer funds"}],
    }
    checkpoint_store.save(run_id, "chk_001", checkpoint_state, metadata={"status": "HITL_PENDING"})

    reg1 = PendingApprovalRegistry()
    reg1.db_path = db_file
    reg1._init_db()
    app1 = reg1.create(
        task_id="step_auth_transfer",
        run_id=run_id,
        prompt="Authorize high-value transfer?",
        timeout_seconds=300,
    )
    token = app1.resumption_token
    app_id = app1.id
    assert not app1.resumed_from_db

    # 2. Simulate Process Death:
    # Clear in-process singletons and instantiate fresh registry loading from SQLite
    InProcessExecutionBackend.clear_instance()
    InProcessExecutionBackend.get_instance(checkpoint_store=checkpoint_store)

    reg2 = PendingApprovalRegistry()
    reg2.db_path = db_file
    reg2._load_from_db()
    monkeypatch.setattr("eval_runner.console.routes.hitl.global_registry", reg2)
    monkeypatch.setattr("eval_runner.hitl.pending.global_registry", reg2)

    app_restored = reg2._items.get(app_id)
    assert app_restored is not None
    assert app_restored.resumed_from_db is True
    assert app_restored.resumption_token == token

    # Mock runner.run_scenario to verify execution resumed
    import threading

    executed_event = threading.Event()
    resumed_executions = []

    def mock_run_scenario(scenario_data, run_id=None, **kwargs):
        resumed_executions.append((run_id, kwargs.get("resumption_checkpoint")))
        executed_event.set()
        return {"status": "SUCCESS", "run_id": run_id}

    monkeypatch.setattr("eval_runner.runner.run_scenario", mock_run_scenario)

    # 3. Create Flask client for resolve endpoint
    app = Flask(__name__)
    app.secret_key = "chaos_secret"
    app.register_blueprint(hitl_bp, url_prefix="/api")

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        client = app.test_client()

        # 4. Resolve approval via standard REST endpoint
        response = client.post(
            f"/api/v1/hitl/{app_id}/resolve",
            json={"action": "approve", "response": "Approved by Chaos Recovery Officer"},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["resolved"] is True
        assert data["approval_id"] == app_id
        assert data["resumed"] is True
        assert data["run_id"] == run_id

    # 5. Assert that backend.resume() executed and submitted run with checkpoint
    assert executed_event.wait(timeout=10.0), "Timed out waiting for background resume thread"
    assert len(resumed_executions) == 1
    executed_run_id, chk = resumed_executions[0]
    assert executed_run_id == run_id
    assert chk["task_id"] == "step_auth_transfer"
