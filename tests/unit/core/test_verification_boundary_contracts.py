"""Verification rejects missing ownership and malformed inputs before evidence access."""

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.manifest import compute_scenario_hash
from eval_runner.verifier import TraceVerifier, verify_trace_certificate


@pytest.mark.parametrize(("run_id", "has_provider"), [("", True), ("run-a", False), ("", False)])
def test_signing_requires_explicit_run_and_provider(run_id, has_provider):
    provider = MagicMock() if has_provider else None
    with pytest.raises(ValueError, match="explicit run_id are required"):
        TraceVerifier.sign_trace_bytes(b"", run_id=run_id, run_store=provider)
    if provider is not None:
        provider.get_trace_bytes.assert_not_called()


@pytest.mark.parametrize(("run_id", "has_provider"), [("", True), ("run-a", False), ("", False)])
def test_byte_verification_requires_explicit_run_and_provider(run_id, has_provider):
    provider = MagicMock() if has_provider else None
    assert not TraceVerifier.verify_trace_bytes(b"", {"run_id": run_id}, run_store=provider)
    if provider is not None:
        provider.get_trace_bytes.assert_not_called()


@pytest.mark.parametrize(
    ("trace", "manifest"),
    [(None, {}), ("not raw bytes", {}), (b"", None), (b"", []), (None, None)],
)
def test_trace_verification_rejects_malformed_inputs_before_provider_access(trace, manifest):
    provider = MagicMock()
    assert not TraceVerifier.verify_trace(trace, manifest, run_store=provider)
    provider.get_trace_bytes.assert_not_called()


@pytest.mark.parametrize(
    ("run", "trace", "manifest", "status"),
    [
        (None, None, None, "NOT_FOUND"),
        (None, b"owned trace", None, "UNVERIFIED"),
        ({"run_id": "run-a"}, None, {"run_id": "run-a"}, "FAILED_VERIFICATION"),
    ],
)
def test_partial_provider_artifacts_are_not_reported_as_absent_or_verified(
    run, trace, manifest, status
):
    provider = MagicMock()
    provider.get_run.return_value = run
    provider.get_trace_bytes.return_value = trace
    provider.get_manifest.return_value = manifest
    result = TraceVerifier.verify_run("run-a", run_store=provider)
    assert result["verification_status"] == status
    assert result["is_valid"] is False
    assert not result.get("verified")


@pytest.mark.parametrize("hash_location", ["top", "metadata", "both"])
def test_certificate_integrity_accepts_declared_scenario_hash_locations(hash_location):
    scenario = {"id": "scenario-boundary", "version": "1.0.0"}
    trace = b'{"event":"run_end"}\n'
    key = Ed25519PrivateKey.generate()
    certificate = {
        "run_id": "run-a",
        "trace_hash": hashlib.sha3_256(trace).hexdigest(),
    }
    if hash_location in {"top", "both"}:
        certificate["scenario_hash"] = compute_scenario_hash(scenario)
    if hash_location in {"metadata", "both"}:
        certificate["metadata"] = {"scenario_hash": compute_scenario_hash(scenario)}
    signature = key.sign(canonical_json_encode(certificate)).hex()
    certificate["provenance_chain"] = [
        {"identity": "boundary-signer", "algorithm": "ED25519", "signature": signature}
    ]
    trust = SimpleNamespace(
        get_public_key=lambda identity: key.public_key() if identity == "boundary-signer" else None
    )

    result = verify_trace_certificate(
        "run-a", trace, cert_data=certificate, scenario_data=scenario, trust_root=trust
    )
    assert result["verified"], result["errors"]
    assert result["authoritative"] is False

    changed_scenario = {**scenario, "version": "2.0.0"}
    rejected = verify_trace_certificate(
        "run-a", trace, cert_data=certificate, scenario_data=changed_scenario, trust_root=trust
    )
    assert rejected["verified"] is False
