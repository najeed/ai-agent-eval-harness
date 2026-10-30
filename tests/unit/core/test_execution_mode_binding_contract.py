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
        ("hybrid", "hybrid", "hybrid", False, True),
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
