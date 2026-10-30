"""A selected signer needs a nonempty trusted identity and bounded envelope inputs."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentv_runtime.signatures import (
    PACKAGE,
    DigestEnvelopeSigningBackend,
    SignatureContractError,
    resolve_policy,
    validate_signing_response,
    verify_artifact_signature,
)
from tests.unit.core.test_digest_signature_contract import remote as remote


@pytest.mark.parametrize("identity", ["", "x" * 5000])
def test_invalid_or_oversized_signer_identity_never_reaches_remote(remote, identity):
    _, raw, policy = remote
    backend = DigestEnvelopeSigningBackend(raw, replace(policy, identity=identity))
    with pytest.raises(SignatureContractError):
        backend.sign_payload(b"{}", purpose=PACKAGE)
    assert not raw.calls


@pytest.mark.parametrize("shape", [None, [], "envelope", 42, True, {}, {"extra": "value"}])
def test_envelope_shape_is_strict_for_json_inputs(remote, shape):
    backend, _, policy = remote
    response = backend.sign_payload(b"{}", purpose=PACKAGE)
    response["envelope"] = shape
    assert not verify_artifact_signature(b"{}", response, policy, PACKAGE)


@pytest.mark.parametrize("wrong_policy", [None, {}, "wrong-identity"])
def test_external_resolver_cannot_change_the_expected_identity(remote, wrong_policy):
    _, _, policy = remote
    value = (
        replace(policy, identity="different-signer")
        if wrong_policy == "wrong-identity"
        else wrong_policy
    )
    trust = SimpleNamespace(get_signature_policy=lambda identity: value)
    with pytest.raises(SignatureContractError, match="different signer identity"):
        resolve_policy(policy.identity, policy.public_key, trust)


def test_external_resolver_policy_must_match_the_selected_public_anchor(remote):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    _, _, policy = remote
    trust = SimpleNamespace(get_signature_policy=lambda identity: policy)
    with pytest.raises(SignatureContractError, match="external public key"):
        resolve_policy(policy.identity, Ed25519PrivateKey.generate().public_key(), trust)


def test_nonzero_base64_padding_bits_are_rejected_even_for_valid_signature_bytes(remote):
    import base64

    backend, _, policy = remote
    response = backend.sign_payload(b"{}", purpose=PACKAGE)
    encoded = response["signature"]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    changed = encoded[:-3] + alphabet[alphabet.index(encoded[-3]) + 1] + "=="
    assert base64.b64decode(changed, validate=True) == base64.b64decode(encoded)
    response["signature"] = changed
    assert not verify_artifact_signature(b"{}", response, policy, PACKAGE)


def test_raw_signing_response_cannot_use_permissive_hex_whitespace(remote):
    _, raw, policy = remote
    signature = raw.key.sign(b"{}").hex() + " "
    with pytest.raises(SignatureContractError, match="IncompleteSignature"):
        validate_signing_response(b"{}", signature, identity=policy.identity, purpose=PACKAGE)


def test_raw_backend_hex_whitespace_is_not_silently_normalized(remote, monkeypatch):
    backend, raw, _ = remote
    original = raw.sign_payload
    monkeypatch.setattr(
        raw, "sign_payload", lambda *args, **kwargs: original(*args, **kwargs) + " "
    )
    with pytest.raises(SignatureContractError, match="64 hex-encoded bytes"):
        backend.sign_payload(b"{}", purpose=PACKAGE)
