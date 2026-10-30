"""Detached packages preserve the issuer's provisional restriction."""

import base64
from copy import deepcopy

import pytest
from flask import Flask

from eval_runner.console.routes.evidence import verify_verification_package
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize(
    ("provisional", "metadata_provisional", "expected_certified"),
    [(False, False, True), (True, False, False), (False, True, False), (True, True, False)],
)
def test_detached_package_cannot_drop_issuer_provisional_restriction(
    finalization_source, provisional, metadata_provisional, expected_certified
):
    provider, scenario = finalization_source
    execution_manifest = provider.get_manifest("run-a")["execution_manifest"]
    trace = provider.get_trace_bytes("run-a")
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    certificate = TraceVerifier.sign_trace_bytes(
        trace,
        run_id="run-a",
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=execution_manifest,
        metadata={"required_oracle_ids": ["oracle-1"], "provisional": metadata_provisional},
        evidence_root_hash=finalization["evidence_root_hash"],
        execution_mode="live",
        provisional=provisional,
    )
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=trace,
        canonical_manifest=execution_manifest,
        scenario_data=scenario,
    )
    assert result["certified"] is expected_certified, result
    assert certificate["provisional"] is (not expected_certified)
    assert certificate["certification"]["outcome"] == (
        "CERTIFIED_PASS" if expected_certified else "PROVISIONAL_PASS"
    )
    if not expected_certified:
        assert result["verified"] is False
        assert any("ProvisionalExecutionCertificationProhibited" in f for f in result["failures"])
        tampered = deepcopy(certificate["verification_package"])
        tampered["metadata"]["provisional"] = False
        forged = VerificationAuthority.verify_certification_artifact(
            tampered,
            raw_trace_bytes=trace,
            canonical_manifest=execution_manifest,
            scenario_data=scenario,
        )
        assert forged["certified"] is False
        assert any("signature" in failure.lower() for failure in forged["failures"])

    app = Flask(__name__)
    with app.test_request_context(
        json={
            "package": certificate["verification_package"],
            "raw_trace_bytes": base64.b64encode(trace).decode("ascii"),
            "execution_manifest": execution_manifest,
            "scenario_data": scenario,
        }
    ):
        response, status = verify_verification_package.__wrapped__()
    payload = response.get_json()
    assert status == (200 if expected_certified else 422)
    assert payload["certified"] is expected_certified
    assert payload["verified"] is expected_certified
