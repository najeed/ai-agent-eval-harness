"""The emitted certificate reference agrees with the certificate-view consumer."""

from copy import deepcopy
from dataclasses import replace

import pytest

from agentv_runtime.manifest import ExecutionManifest
from agentv_runtime.package import VerificationPackage
from eval_runner.certification_truth import _digest
from eval_runner.identity import IdentityService
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("view_mode", ["live", "hybrid"])
def test_certificate_hash_projection_preserves_execution_mode(finalization_source, view_mode):
    provider, scenario = finalization_source
    manifest = provider.get_manifest("run-a")["execution_manifest"]
    raw = provider.get_trace_bytes("run-a")
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    certificate = TraceVerifier.sign_trace_bytes(
        raw,
        run_id="run-a",
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=manifest,
        metadata={"required_oracle_ids": ["oracle-1"]},
        execution_mode="live",
        evidence_root_hash=finalization["evidence_root_hash"],
    )
    package = certificate["verification_package"]
    authoritative = VerificationAuthority.verify_certification_artifact(
        package, raw_trace_bytes=raw, canonical_manifest=manifest, scenario_data=scenario
    )
    assert authoritative["certified"], authoritative["failures"]
    # This explicit legacy diagnostic projection resolves the certificate
    # reference only. The complete signed package was checked above; an
    # omitted physical manifest binding must never imply certification here.
    projection = {
        key: value
        for key, value in manifest.items()
        if key not in {"agent_config", "runtime_config", "environment"}
    }
    view = {**certificate, **projection, "execution_mode": view_mode}
    diagnostic_package = deepcopy(package)
    diagnostic_package["manifest_hash"] = ""
    diagnostic_package = (
        VerificationPackage.from_dict(diagnostic_package)
        .sign(IdentityService.get_private_key("system_id", auto_provision=False))
        .to_dict()
    )
    diagnostic = VerificationAuthority.verify_package_artifacts(
        diagnostic_package,
        raw_trace_bytes=raw,
        canonical_manifest=view,
        scenario_data=scenario,
        require_signature=False,
    )
    assert diagnostic["verified"] is (view_mode == "live"), diagnostic["failures"]
    assert diagnostic["authoritative"] is False
    assert diagnostic["certified"] is False
    if view_mode != "live":
        assert any("CertificateHashMismatch" in failure for failure in diagnostic["failures"])


@pytest.mark.parametrize("typed_manifest", [False, True])
@pytest.mark.parametrize(
    ("defect", "failure"),
    [
        ("missing_projection", "CertificateArtifactMissing"),
        ("missing_field", "CertificateArtifactMissing"),
        ("missing_hash", "CertificateHashMissing"),
        ("changed_hash", "CertificateHashMismatch"),
        ("changed_projection", "CertificateHashMismatch"),
        ("rebound_run", "CertificateProjectionMismatch:run_id"),
        ("rebound_compliance", "CertificateProjectionMismatch:compliance"),
    ],
)
def test_authoritative_certificate_projection_is_mandatory_and_recomputed(
    finalization_source, typed_manifest, defect, failure
):
    provider, scenario = finalization_source
    raw = provider.get_trace_bytes("run-a")
    certificate = TraceVerifier.sign_trace_bytes(
        raw, run_id="run-a", run_store=provider, execution_mode="live"
    )
    package = VerificationPackage.from_dict(deepcopy(certificate["verification_package"]))
    projection = package.metadata["certificate_projection"]
    if defect == "missing_projection":
        package.metadata.pop("certificate_projection")
    elif defect == "missing_field":
        projection.pop("timestamp")
    elif defect == "missing_hash":
        package = replace(package, certificate_hash="")
    elif defect == "changed_hash":
        package = replace(package, certificate_hash="sha3_256:tampered")
    elif defect == "changed_projection":
        projection["compliance"]["score"] = 0.125
    elif defect == "rebound_run":
        projection["run_id"] = "another-run"
        package = replace(package, certificate_hash=_digest(projection))
    elif defect == "rebound_compliance":
        projection["compliance"]["score"] = 0.125
        package = replace(package, certificate_hash=_digest(projection))
    # A valid package signature must not hide a broken certificate commitment.
    signed = package.sign(IdentityService.get_private_key("system_id", auto_provision=False))
    assert signed.verify_signature()
    manifest = certificate["execution_manifest"]
    result = VerificationAuthority.verify_certification_artifact(
        signed,
        raw_trace_bytes=raw,
        canonical_manifest=ExecutionManifest.from_dict(manifest) if typed_manifest else manifest,
        scenario_data=scenario,
    )
    assert result["certified"] is False
    assert any(failure in item for item in result["failures"]), result


def test_message_certification_verifies_with_public_trust_without_issuer_secrets(
    finalization_source, monkeypatch
):
    provider, scenario = finalization_source
    raw = provider.get_trace_bytes("run-a")
    certificate = TraceVerifier.sign_trace_bytes(
        raw, run_id="run-a", run_store=provider, execution_mode="live"
    )

    def private_material_forbidden(*args, **kwargs):
        raise AssertionError("Detached verification must not read issuer secrets")

    monkeypatch.setattr(IdentityService, "get_private_key", private_material_forbidden)
    monkeypatch.setattr(
        "eval_runner.state_authority.get_state_authority_trust_key", private_material_forbidden
    )
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=raw,
        canonical_manifest=ExecutionManifest.from_dict(certificate["execution_manifest"]),
        scenario_data=scenario,
    )
    assert result["certified"], result["failures"]
