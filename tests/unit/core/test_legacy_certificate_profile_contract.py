"""Valid historical signatures cannot authorize an incomplete certificate profile."""

import base64

from flask import Flask

from agentv_runtime.package import VerificationPackage
from eval_runner.console.routes.evidence import verify_verification_package
from eval_runner.identity import IdentityService
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


def test_legacy_signed_package_profile_is_explicitly_non_authoritative(finalization_source):
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
        execution_mode="live",
        provisional=True,
        metadata={"required_oracle_ids": ["oracle-1"]},
        evidence_root_hash=finalization["evidence_root_hash"],
    )
    legacy = certificate["verification_package"]
    legacy["metadata"].pop("certificate_profile")
    # Reproduce the pre-fix issuer: the certificate was provisional, while
    # the detached package's metadata claimed otherwise. Its signature is real.
    legacy["metadata"]["provisional"] = False
    key = IdentityService.get_private_key("system_id", auto_provision=False)
    legacy["signature"] = key.sign(
        VerificationPackage.from_dict(legacy).canonical_payload_bytes()
    ).hex()
    key.public_key().verify(
        bytes.fromhex(legacy["signature"]),
        VerificationPackage.from_dict(legacy).canonical_payload_bytes(),
    )
    inputs = {
        "raw_trace_bytes": trace,
        "canonical_manifest": execution_manifest,
        "scenario_data": scenario,
    }
    authoritative = VerificationAuthority.verify_certification_artifact(legacy, **inputs)
    assert authoritative["verified"] is False
    assert authoritative["certified"] is False
    assert authoritative["authoritative"] is False
    assert any("UnsupportedCertificateProfile" in reason for reason in authoritative["failures"])
    diagnostic = VerificationAuthority.verify_package(legacy, require_signature=False, **inputs)
    assert diagnostic["verified"] is True, diagnostic["failures"]
    assert diagnostic["certified"] is False
    assert diagnostic["authoritative"] is False
    artifacts = VerificationAuthority.verify_package_artifacts(legacy, **inputs)
    assert artifacts["verified"] is True, artifacts["failures"]
    assert artifacts["certified"] is False
    assert artifacts["authoritative"] is False
    assert artifacts["status"] == "DIAGNOSTIC_VALID"

    app = Flask(__name__)
    with app.test_request_context(
        json={
            "package": legacy,
            "raw_trace_bytes": base64.b64encode(trace).decode("ascii"),
            "execution_manifest": execution_manifest,
            "scenario_data": scenario,
        }
    ):
        response, status = verify_verification_package.__wrapped__()
    payload = response.get_json()
    assert status == 422
    assert payload["certified"] is False
    assert payload["authoritative"] is False
