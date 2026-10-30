"""Certificate outcome labels follow actual execution mode and oracle outcome."""

import pytest

from eval_runner.verifier import TraceVerifier, verify_trace_certificate
from tests.unit.core.test_certification_service_and_trust_boundary import _seed_run
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize(
    ("mode", "provisional", "outcome", "expected"),
    [
        ("live", False, "pass", "CERTIFIED_PASS"),
        ("live", True, "pass", "PROVISIONAL_PASS"),
        ("simulated", False, "pass", "PROVISIONAL_PASS"),
        ("record_replay", False, "pass", "PROVISIONAL_PASS"),
        ("live", False, "fail", "ATTESTED_FAIL"),
    ],
)
def test_signing_outcome_tracks_execution_and_oracles(
    finalization_source, mode, provisional, outcome, expected
):
    provider, _ = finalization_source
    run_id = "outcome-run"
    scenario = _seed_run(provider, run_id, outcome=outcome, mode=mode)
    trace = provider.get_trace_bytes(run_id)
    execution_manifest = provider.get_manifest(run_id)["execution_manifest"]
    finalization = provider.get_events(run_id, offset=0, limit=100)[-1]["data"]
    certificate = TraceVerifier.sign_trace_bytes(
        trace,
        run_id=run_id,
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=execution_manifest,
        metadata={"required_oracle_ids": ["oracle-1"]},
        evidence_root_hash=finalization["evidence_root_hash"],
        execution_mode=mode,
        provisional=provisional,
        compliance_status=outcome,
        compliance_score=1.0 if outcome == "pass" else 0.0,
    )
    assert certificate["certification"]["outcome"] == expected
    result = verify_trace_certificate(
        run_id,
        trace,
        cert_data=certificate,
        scenario_data=scenario,
        trace_only=False,
    )
    assert result["verified"], result["errors"]
