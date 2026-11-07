"""A signed mode claim cannot override the execution manifest's recorded mode."""

import json

import pytest

from agentv_runtime.manifest import ExecutionManifest
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_certification_service_and_trust_boundary import _seed_run
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize(
    ("actual_mode", "trace_mode", "claimed_mode", "trace_provisional", "certified"),
    [
        ("live", "live", "live", False, True),
        ("hybrid", "hybrid", "hybrid", False, False),
        ("simulated", "simulated", "live", False, False),
        ("record_replay", "record_replay", "live", False, False),
        ("live", "live", "hybrid", False, False),
        ("simulated", "live", "live", False, False),
        ("live", "simulated", "live", False, False),
        ("live", "live", "live", True, False),
        ("live", None, "live", False, False),
    ],
)
@pytest.mark.parametrize("typed_manifest", [False, True])
def test_signed_execution_mode_claim_must_match_actual_manifest(
    finalization_source,
    actual_mode,
    trace_mode,
    claimed_mode,
    trace_provisional,
    certified,
    typed_manifest,
):
    provider, _ = finalization_source
    scenario = _seed_run(provider, "mode-run", mode=actual_mode)
    execution_manifest = provider.get_manifest("mode-run")["execution_manifest"]
    lines = provider.get_trace_bytes("mode-run").splitlines(keepends=True)
    start = json.loads(lines[0])
    if trace_mode is None:
        start.pop("execution_mode")
    else:
        start["execution_mode"] = trace_mode
    start["provisional"] = trace_provisional
    lines[0] = json.dumps(start, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    trace = b"".join(lines)
    from eval_runner.utils import crypto

    provider.update_run_status(
        "mode-run",
        "OPEN",
        details={
            "evidence_capture": {
                "complete": True,
                "event_count": len(lines),
                "terminal_seq": len(lines),
                "trace_hash": "sha3_256:" + crypto.checksum(trace),
            }
        },
    )

    class TraceView:
        def get_trace_bytes(self, run_id, context=None):
            return trace

        def get_run(self, run_id, context=None):
            return provider.get_run(run_id, context=context)

        def get_manifest(self, run_id, context=None):
            return provider.get_manifest(run_id, context=context)

    finalization = provider.get_events("mode-run", offset=0, limit=100)[-1]["data"]
    certificate = TraceVerifier.sign_trace_bytes(
        trace,
        run_id="mode-run",
        run_store=TraceView(),
        scenario_data=scenario,
        execution_manifest=execution_manifest,
        execution_mode=claimed_mode,
        metadata={"required_oracle_ids": ["oracle-1"]},
        evidence_root_hash=finalization["evidence_root_hash"],
    )
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=trace,
        canonical_manifest=(
            ExecutionManifest.from_dict(execution_manifest)
            if typed_manifest
            else execution_manifest
        ),
        scenario_data=scenario,
    )
    assert result["certified"] is certified, result
    if not certified:
        reason = (
            "ProvisionalExecutionCertificationProhibited"
            if trace_provisional
            else "ExecutionModeMissing"
            if trace_mode is None
            else "ExecutionModeMismatch"
        )
        assert any(reason in failure for failure in result["failures"])


def test_simulated_tool_provenance_rejects_authoritative_live_certification(finalization_source):
    from eval_runner.services.certification import execute_industrial_certification

    provider, _ = finalization_source
    run_id = "simulated-tool-live-run"
    simulated_tool_event = {
        "event": "tool_result",
        "data": {
            "step": 1,
            "tool": "mock_balance_check",
            "result": {"balance": 100},
            "provenance": "simulated",
        },
    }
    scenario = _seed_run(provider, run_id, mode="live", extra_events=[simulated_tool_event])

    with pytest.raises(ValueError, match="ProviderTruthLevelNotLive"):
        execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)


def test_detached_verifier_rejects_simulated_tool_provenance_in_live_run(finalization_source):
    provider, _ = finalization_source
    run_id = "simulated-tool-detached-run"
    simulated_tool_event = {
        "event": "tool_result",
        "data": {
            "step": 1,
            "tool": "mock_balance_check",
            "result": {"balance": 100},
            "provenance": "simulated",
        },
    }
    scenario = _seed_run(provider, run_id, mode="live", extra_events=[simulated_tool_event])
    trace = provider.get_trace_bytes(run_id)
    execution_manifest = provider.get_manifest(run_id)["execution_manifest"]
    finalization = provider.get_events(run_id, offset=0, limit=100)[-1]["data"]

    class TraceView:
        def get_trace_bytes(self, rid, context=None):
            return trace

        def get_run(self, rid, context=None):
            return provider.get_run(rid, context=context)

        def get_manifest(self, rid, context=None):
            return provider.get_manifest(rid, context=context)

    certificate = TraceVerifier.sign_trace_bytes(
        trace,
        run_id=run_id,
        run_store=TraceView(),
        scenario_data=scenario,
        execution_manifest=execution_manifest,
        execution_mode="live",
        metadata={"required_oracle_ids": ["oracle-1"]},
        evidence_root_hash=finalization["evidence_root_hash"],
    )
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=trace,
        canonical_manifest=execution_manifest,
        scenario_data=scenario,
    )
    assert result["certified"] is False
    assert any("SimulatedToolProvenanceInLiveRun" in f for f in result["failures"])


@pytest.mark.asyncio
async def test_scenario_defined_tool_provenance_is_simulated_even_in_live_mode(tmp_path):
    """ToolSandbox must classify scenario-defined tools as simulated
    even if scenario claims live.
    """
    from eval_runner.tool_sandbox import ToolSandbox

    scenario = {
        "execution_mode": "live",
        "tools": {
            "query_account": {
                "output": {"balance": 500},
                "state_changes": [{"path": "query_count", "value": 1}],
            }
        },
    }
    sandbox = ToolSandbox(scenario)
    assert sandbox.get_tool_provenance("query_account") == "simulated"
    assert sandbox.has_simulated_tools is False

    # Executing the scenario-defined tool marks simulated execution
    result = await sandbox.execute("query_account", {})
    assert result == {"balance": 500}
    assert sandbox.has_simulated_tools is True


def test_session_manager_defaults_provenance_to_simulated():
    """SessionManager._extract_provenance must default to 'simulated' when absent."""
    from eval_runner.session import SessionManager

    session = SessionManager("test-session-prov", {"execution_mode": "live"})
    # Output without provenance defaults to simulated
    assert session._extract_provenance("test_tool", result={"balance": 100}) == "simulated"
    assert session._extract_provenance("test_tool", result="plain string result") == "simulated"
    assert session._extract_provenance("test_tool", result=None) == "simulated"
    # Output with explicit live provenance is recognized
    assert (
        session._extract_provenance("test_tool", result={"balance": 100, "provenance": "live"})
        == "live"
    )
    assert (
        session._extract_provenance("test_tool", result={"provenance": "simulated"}) == "simulated"
    )
