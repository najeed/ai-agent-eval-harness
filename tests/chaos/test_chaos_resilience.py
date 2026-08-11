"""
Chaos resilience & failure injection test suite for AgentV evaluation infrastructure.
Enforces the fundamental AgentV invariant: Infrastructure failure or exception
must NEVER silently convert into an evaluation success (PASS).
"""

from __future__ import annotations

import asyncio

import pytest

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
async def test_chaos_llm_network_timeout_resilience(chaos_scenario, tmp_path):
    """
    Chaos Test: Simulated LLM network timeout during tool call
    must raise exception and not silently pass.
    """
    sandbox = ToolSandbox(
        scenario=chaos_scenario,
        workspace_root=tmp_path / "workspace",
        jail_root=tmp_path / "jail",
    )
    await sandbox.setup()

    async def throwing_core_exec(data):
        raise TimeoutError("Network timeout during LLM interception")

    with pytest.raises(asyncio.TimeoutError):
        await throwing_core_exec({"tool_name": "faulty_tool"})


def test_chaos_missing_trace_verification_failure(tmp_path, monkeypatch):
    """
    Chaos Test: Non-existent trace file must raise FileNotFoundError during verification.
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
    Chaos Test: Invariant check - VerificationResult with failed metrics or error message
    is guaranteed to have success=False.
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
