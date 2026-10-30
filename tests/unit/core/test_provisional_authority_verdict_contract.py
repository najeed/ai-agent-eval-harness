"""A valid live signature cannot override an issuer's provisional designation."""

import pytest

from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import TraceVerifier, verify_trace_certificate
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("provisional", [False, True])
def test_live_signed_certificate_honors_explicit_provisional_designation(
    finalization_source, provisional
):
    provider, scenario = finalization_source
    execute_industrial_certification("run-a", run_store=provider, scenario_data=scenario)
    raw = provider.get_trace_bytes("run-a")
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    certificate = TraceVerifier.sign_trace_bytes(
        raw,
        run_id="run-a",
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=provider.get_manifest("run-a")["execution_manifest"],
        metadata={"required_oracle_ids": ["oracle-1"]},
        evidence_root_hash=finalization["evidence_root_hash"],
        execution_mode="live",
        provisional=provisional,
        compliance_status="pass",
        compliance_score=1.0,
    )
    integrity = verify_trace_certificate(
        "run-a", raw, cert_data=certificate, scenario_data=scenario, trace_only=False
    )
    assert integrity["verified"], integrity["errors"]

    class CertificateView:
        def get_run(self, run_id, context=None):
            return provider.get_run(run_id, context=context)

        def get_manifest(self, run_id, context=None):
            return certificate

        def get_trace_bytes(self, run_id, context=None):
            return provider.get_trace_bytes(run_id, context=context)

    result = TraceVerifier.verify_run("run-a", run_store=CertificateView(), scenario_data=scenario)

    assert result["verified"] is not provisional
    assert result["is_valid"] is not provisional
    assert result["provisional"] is provisional
    assert result["verification_status"] == ("FAILED_VERIFICATION" if provisional else "VERIFIED")
