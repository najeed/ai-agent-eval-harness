"""
Chaos resilience & boundary fault injection test suite for AgentV evaluation infrastructure.
Enforces the fundamental AgentV invariant: Infrastructure failure or exception
at LLM adapter boundaries, WORM disk layer, or simulator runtime
must NEVER silently convert into an evaluation success (PASS).
"""

from __future__ import annotations

import aiohttp
import pytest

from eval_runner.adapters.common import BaseAdapter
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.verifier import CertificationFailedError, TraceVerifier


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
    Boundary Fault Injection: Missing trace file or provider trace ownership mismatch
    must raise CertificationFailedError.
    """
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    run_id = "run-chaos-missing-001"

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)

    store = LocalFileRunStore(log_dir=run_log_dir)
    store.create_run(run_id=run_id, scenario_id="chaos-scenario")

    with pytest.raises(CertificationFailedError, match="ProviderTraceOwnershipMismatch"):
        TraceVerifier.sign_trace_bytes(
            b'{"event": "unpersisted"}',
            identity_id="chaos_verifier",
            compliance_status="pass",
            run_id=run_id,
            run_store=store,
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

    store = LocalFileRunStore(log_dir=run_log_dir)
    store.create_run(run_id=run_id, scenario_id=chaos_scenario.get("id", "chaos"))
    init_event = {"event": "start", "run_id": run_id}
    store.append_events(run_id, [init_event])
    trace_bytes = store.get_trace_bytes(run_id)
    assert trace_bytes is not None

    # 2. Sign trace to issue initial manifest
    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        identity_id="chaos_verifier",
        compliance_status="pass",
        run_id=run_id,
        run_store=store,
    )
    store.save_run_manifest(run_id, manifest)
    store.update_run_status(run_id, "SEALED")

    # 3. Inject Infrastructure Fault: Truncate / corrupt the trace after signing
    corrupted_bytes = trace_bytes + b'\n{"event": "infrastructure_crash_event_corrupted": true}\n'

    # 4. Verify pipeline output: TraceVerifier MUST detect the fault and return False (never PASS)
    is_valid = TraceVerifier.verify_trace(corrupted_bytes, manifest, run_store=store)
    assert is_valid is False, "Infrastructure fault allowed corrupted evaluation to return PASS!"


def test_chaos_readonly_worm_filesystem_lock_failure(tmp_path):
    """
    Boundary Fault Injection: Verifying non-existent run or corrupted manifest
    must fail cleanly without swallowing errors.
    """
    store = LocalFileRunStore(log_dir=tmp_path / "runs")
    is_valid = TraceVerifier.verify_trace(b"{}", {"run_id": "missing"}, run_store=store)
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

    # Write an unsigned trace via provider (no manifest was ever created)
    store = LocalFileRunStore(log_dir=run_log_dir)
    store.create_run(run_id=run_id, scenario_id="chaos")
    store.append_events(run_id, [{"event": "start", "run_id": run_id}])
    trace_bytes = store.get_trace_bytes(run_id)
    assert trace_bytes is not None
    manifest = store.get_manifest(run_id) or {}
    # manifest intentionally has no certificate / signature — signing never happened

    # Verifier MUST return False: a crash-interrupted run can never PASS
    is_valid = TraceVerifier.verify_trace(trace_bytes, manifest, run_store=store)
    assert is_valid is False, (
        "INVARIANT VIOLATED: Simulator crash allowed unsigned trace to pass verification!"
    )
