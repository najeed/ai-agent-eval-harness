"""Signed records are complete before export, and diagnostic decoding preserves their bindings."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.interfaces import SigningBackend


def draft_record(finalization_hash=""):
    return EvaluatorFinalizationRecord(
        finalization_id="finalization",
        run_id="run",
        execution_manifest_hash="sha3_256:" + "1" * 64,
        scenario_id="scenario",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:" + "2" * 64,
        evaluator_identity="evaluator",
        evaluator_config_hash="sha3_256:" + "3" * 64,
        required_oracle_ids=["balance"],
        evidence_root_hash="sha3_256:" + "4" * 64,
        outcome="pass",
        score=1.0,
        terminal_seq=4,
        finalized_at="2026-10-29T00:00:00Z",
        finalization_hash=finalization_hash,
    )


@pytest.mark.parametrize("draft_hash", ["", "sha3_256:" + "0" * 64])
def test_signing_returns_complete_object_with_recomputed_hash(draft_hash):
    private_key = Ed25519PrivateKey.generate()

    signed = draft_record(draft_hash).sign(private_key)

    assert signed.finalization_hash == signed.compute_finalization_hash()
    assert signed.evaluator_signature
    restored = EvaluatorFinalizationRecord.from_dict(
        signed.to_dict(), require_authoritative=True, public_key=private_key.public_key()
    )
    assert restored.finalization_hash == signed.finalization_hash


@pytest.mark.parametrize("signature_field", ["evaluator_signature", "signature"])
@pytest.mark.parametrize("manifest_field", ["execution_manifest_hash", "manifest_hash"])
def test_diagnostic_decode_preserves_hash_and_signature_for_explicit_anchored_verification(
    signature_field,
    manifest_field,
):
    private_key = Ed25519PrivateKey.generate()
    signed = draft_record().sign(private_key)
    payload = signed.to_dict()
    payload.pop("evaluator_signature")
    payload.pop("execution_manifest_hash")
    payload.pop("manifest_hash")
    payload[manifest_field] = signed.execution_manifest_hash
    payload[signature_field] = signed.evaluator_signature

    decoded = EvaluatorFinalizationRecord.from_dict(payload, require_authoritative=False)

    assert decoded.finalization_hash == signed.finalization_hash
    assert decoded.execution_manifest_hash == signed.execution_manifest_hash
    assert decoded.evaluator_signature == signed.evaluator_signature
    assert decoded.verify_signature(public_key=private_key.public_key())


@pytest.mark.parametrize("signature_field", ["signature", "sig"])
def test_signing_backend_response_wrappers_preserve_the_canonical_signature(signature_field):
    private_key = Ed25519PrivateKey.generate()
    selectors = []

    class CanonicalSigner(SigningBackend):
        def sign_payload(self, payload, key_identifier=None, **kwargs):
            selectors.append(key_identifier)
            return private_key.sign(payload).hex()

        def verify_signature(self, payload, signature, public_key_identifier=None, **kwargs):
            private_key.public_key().verify(bytes.fromhex(signature), payload)
            return True

    class UnversionedWrappedSigner(SigningBackend):
        def sign_payload(self, payload, key_identifier=None, **kwargs):
            return {signature_field: private_key.sign(payload).hex()}

        def verify_signature(self, payload, signature, public_key_identifier=None, **kwargs):
            return True

    signed = draft_record().sign(CanonicalSigner())

    assert selectors == ["evaluator"]
    assert signed.verify_signature(public_key=private_key.public_key())
    assert signed.finalization_hash == signed.compute_finalization_hash()

    with pytest.raises(
        ValueError,
        match=(
            "External signature policy|Invalid or unauthorized|"
            "Pre-existing trusted private key|Expected an externally anchored Ed25519 public key"
        ),
    ):
        draft_record().sign(UnversionedWrappedSigner())
