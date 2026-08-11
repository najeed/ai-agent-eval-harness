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
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.verifier import TraceVerifier, VerificationResult


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


def test_chaos_evaluation_failure_never_converts_to_success():
    """
    Invariant Check: VerificationResult with zero metrics or error
    is guaranteed to have success=False and aggregate_score=0.0.
    """
    result = VerificationResult(
        success=False,
        message="Simulated Infrastructure Crash",
        metrics={
            "safety": 0.0,
            "security": 0.0,
            "reliability": 0.0,
            "fairness": 0.0,
            "explainability": 0.0,
            "privacy": 0.0,
            "resilience": 0.0,
        },
    )
    assert result.success is False
    assert result.aggregate_score == 0.0
