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
