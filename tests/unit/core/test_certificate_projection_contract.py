"""The emitted certificate reference agrees with the certificate-view consumer."""

from copy import deepcopy

import pytest

from agentv_runtime.package import VerificationPackage
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
