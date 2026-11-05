"""Raw primitives cannot be mistaken for purpose-bound artifact signatures."""

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.package import VerificationPackage
from agentv_runtime.signatures import CERTIFICATE, FINALIZATION, PACKAGE, sign_digest_envelope
from eval_runner.reference.signing import LocalEd25519SigningBackend


def test_real_raw_signatures_cannot_verify_as_finalization_or_package():
    key = Ed25519PrivateKey.generate()
    record = EvaluatorFinalizationRecord(
        finalization_id="finalization-run",
        execution_manifest_hash="sha3_256:" + "1" * 64,
        scenario_version="1.0.0",
        scenario_hash="sha3_256:" + "2" * 64,
        evaluator_config_hash="sha3_256:" + "3" * 64,
        required_oracle_ids=["oracle-1"],
        evidence_root_hash="sha3_256:" + "4" * 64,
        evaluator_identity="evaluator",
        run_id="run",
        scenario_id="scenario",
        outcome="pass",
        score=1.0,
    ).sign(key)
    assert record.evaluator_signature["profile"] == "agentv.signature.digest-envelope.v1"
    assert record.verify_signature(public_key=key.public_key())
    raw_record = replace(
        record, evaluator_signature=key.sign(record.canonical_payload_bytes()).hex()
    )
    assert not raw_record.verify_signature(public_key=key.public_key())
    package = VerificationPackage.from_dict(
        {"scenario_id": "scenario", "signer_identity": "issuer"}
    ).sign(key)
    pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    assert package.signature["profile"] == "agentv.signature.digest-envelope.v1"
    assert package.verify_signature(public_key_pem=pem)
    raw_package = replace(package, signature=key.sign(package.canonical_payload_bytes()).hex())
    assert not raw_package.verify_signature(public_key_pem=pem)


@pytest.mark.parametrize("purpose", [CERTIFICATE, PACKAGE, FINALIZATION])
def test_local_primitive_requires_an_envelope_at_artifact_boundary(purpose):
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    backend = LocalEd25519SigningBackend()
    raw = backend.sign_payload(b"{}", private)
    assert not backend.verify_signature(b"{}", raw, public, purpose=purpose)
    response = backend.sign_payload(b"{}", private, purpose=purpose)
    assert backend.verify_signature(b"{}", response, public, purpose=purpose)
    other = PACKAGE if purpose != PACKAGE else CERTIFICATE
    assert not backend.verify_signature(b"{}", response, public, purpose=other)


def test_local_envelope_signing_cannot_ignore_a_trust_policy_error(monkeypatch):
    def invalid_policy(*args, **kwargs):
        raise ValueError("Malformed external signature policy")

    monkeypatch.setattr("agentv_runtime.signatures.resolve_policy", invalid_policy)
    with pytest.raises(ValueError, match="Malformed external signature policy"):
        sign_digest_envelope(
            b"{}", Ed25519PrivateKey.generate(), identity="issuer", purpose=CERTIFICATE
        )
