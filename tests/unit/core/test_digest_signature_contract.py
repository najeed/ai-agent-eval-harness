"""Digest-envelope protocol, remote failure behavior, and offline public verification."""

import base64
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.signatures import (
    CERTIFICATE,
    FINALIZATION,
    PACKAGE,
    PROFILE,
    DigestEnvelopeSigningBackend,
    SignatureContractError,
    SignaturePolicy,
    certificate_payload_bytes,
    fingerprint,
    unsigned_envelope,
    verify_artifact_signature,
)
from eval_runner import config, runtime_services
from eval_runner.identity import IdentityService
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import (
    CertificationFailedError,
    CoreTraceSigner,
    TraceVerifier,
    verify_trace_certificate,
)
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


class BoundedRemote:
    """A remote boundary with real signatures and the same RAW size constraint as KMS."""

    requires_private_key_material = False

    def __init__(self, key):
        self.key = key
        self.calls = []
        self.outage = False

    def can_sign(self):
        return True

    def sign_payload(self, payload, key_identifier=None, **kwargs):
        self.calls.append(payload)
        if self.outage:
            raise ConnectionError("remote unavailable")
        if not 1 <= len(payload) <= 4096:
            raise ValueError("RAW payload exceeds remote limit")
        return self.key.sign(payload).hex()


@pytest.fixture
def remote():
    key = Ed25519PrivateKey.generate()
    policy = SignaturePolicy(
        "evaluator", "sha256:" + fingerprint(key.public_key()), key.public_key()
    )
    raw = BoundedRemote(key)
    return DigestEnvelopeSigningBackend(raw, policy), raw, policy


def test_large_payload_is_an_envelope_signature_with_independent_offline_verification(
    remote, tmp_path
):
    backend, raw, policy = remote
    payload = canonical_json_encode({"large": "x" * 25000})
    with pytest.raises(ValueError, match="remote limit"):
        raw.sign_payload(payload)
    response = backend.sign_payload(payload, purpose=PACKAGE)
    assert verify_artifact_signature(payload, response, policy, PACKAGE)
    assert 1 <= len(raw.calls[-1]) <= 4096
    assert raw.calls[-1] == canonical_json_encode(response["envelope"])
    # A separate process imports neither Core nor its signer/verifier implementation.
    artifact = tmp_path / "offline.json"
    artifact.write_text(
        json.dumps(
            {
                "payload": payload.decode(),
                "response": response,
                "public_key": policy.public_key.public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                ).decode(),
                "key_id": policy.key_id,
            }
        )
    )
    reviewer = r"""
import base64, hashlib, json, sys
from cryptography.hazmat.primitives import serialization
d=json.load(open(sys.argv[1]))
r=d["response"]; e=r["envelope"]
assert set(r)=={"profile","envelope","signature"}
assert r["profile"]==e["profile"]=="agentv.signature.digest-envelope.v1"
assert type(e["version"]) is int and e["version"]==1
assert e["purpose"]=="agentv.verification-package"
assert e["payload_projection"]=="agentv.verification-package.unsigned.v1"
assert e["envelope_canonicalization"]==e["payload_canonicalization"]=="RFC8785"
assert e["payload_digest_algorithm"]==e["fingerprint_algorithm"]=="sha256"
assert e["payload_digest_encoding"]=="hex-lowercase"
assert e["payload_digest"]==hashlib.sha256(d["payload"].encode()).hexdigest()
assert e["signing_algorithm"]=="Ed25519"
assert e["signing_semantics"]=="raw-ed25519-over-canonical-envelope-bytes"
assert e["signer_identity"]=="evaluator" and e["key_id"]==d["key_id"]
assert e["public_key_encoding"]=="spki-der"
assert e["signature_encoding"]=="base64-rfc4648-padded" and e["signature_length"]==64
key=serialization.load_pem_public_key(d["public_key"].encode())
der=key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
assert e["public_key_fingerprint"]==hashlib.sha256(der).hexdigest()
sig=base64.b64decode(r["signature"],validate=True)
assert len(sig)==64
key.verify(sig,json.dumps(e,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode())
"""
    subprocess.run(
        [sys.executable, "-P", "-c", reviewer, str(artifact)],
        cwd=tmp_path,
        check=True,
        timeout=20,
    )


@pytest.mark.parametrize(
    "field",
    list(
        unsigned_envelope(
            b"{}",
            SignaturePolicy(
                "test",
                "sha256:" + fingerprint((key := Ed25519PrivateKey.generate()).public_key()),
                key.public_key(),
            ),
            PACKAGE,
        )
    ),
)
def test_every_envelope_binding_is_enforced_even_with_a_genuine_signature(remote, field):
    backend, raw, policy = remote
    payload = b'{"number":1}'
    response = backend.sign_payload(payload, purpose=PACKAGE)
    envelope = response["envelope"]
    envelope[field] = 2 if isinstance(envelope[field], int) else "altered"
    # A valid signature must not substitute for policy/projection/digest reconciliation.
    response["signature"] = base64.b64encode(raw.key.sign(canonical_json_encode(envelope))).decode()
    assert not verify_artifact_signature(payload, response, policy, PACKAGE)


@pytest.mark.parametrize(
    "corruption",
    [
        "payload",
        "key",
        "unknown_profile",
        "missing_profile",
        "unknown_field",
        "missing_field",
        "short_signature",
        "long_signature",
        "noncanonical_base64",
        "hex_signature",
        "bool_version",
        "extra_response_field",
    ],
)
def test_malformed_or_ambiguous_responses_do_not_downgrade(remote, corruption):
    backend, _, policy = remote
    payload = b"{}"
    response = backend.sign_payload(payload, purpose=PACKAGE)
    if corruption == "payload":
        payload = b'{"changed":true}'
    elif corruption == "key":
        policy = replace(policy, public_key=Ed25519PrivateKey.generate().public_key())
    elif corruption == "unknown_profile":
        response["profile"] = "unknown"
    elif corruption == "missing_profile":
        response.pop("profile")
    elif corruption == "unknown_field":
        response["envelope"]["unknown"] = "extra"
    elif corruption == "missing_field":
        response["envelope"].pop("purpose")
    elif corruption == "short_signature":
        response["signature"] = base64.b64encode(b"x" * 63).decode()
    elif corruption == "long_signature":
        response["signature"] = base64.b64encode(b"x" * 65).decode()
    elif corruption == "noncanonical_base64":
        response["signature"] += "\n"
    elif corruption == "hex_signature":
        response["signature"] = base64.b64decode(response["signature"]).hex()
    elif corruption == "bool_version":
        response["envelope"]["version"] = True
    else:
        response["extra"] = True
    assert not verify_artifact_signature(payload, response, policy, PACKAGE)


@pytest.mark.parametrize("restriction", ["revoked", "expired", "future", "purpose", "profile"])
def test_external_trust_policy_restricts_valid_signatures(remote, restriction):
    backend, _, policy = remote
    response = backend.sign_payload(b"{}", purpose=PACKAGE)
    changes = {
        "revoked": {"revoked": True},
        "expired": {"not_after": datetime.now(UTC) - timedelta(seconds=1)},
        "future": {"not_before": datetime.now(UTC) + timedelta(hours=1)},
        "purpose": {"permitted_purposes": (CERTIFICATE,)},
        "profile": {"permitted_profiles": ("ed25519-raw",)},
    }
    assert not verify_artifact_signature(
        b"{}", response, replace(policy, **changes[restriction]), PACKAGE
    )


def test_raw_legacy_evidence_requires_explicit_policy(remote):
    _, raw, policy = remote
    signature = raw.key.sign(b"{}").hex()
    assert verify_artifact_signature(b"{}", signature, policy, PACKAGE)
    assert not verify_artifact_signature(
        b"{}", signature, replace(policy, allow_legacy_raw=False), PACKAGE
    )


def test_remote_outage_and_wrong_key_fail_without_local_fallback(remote):
    backend, raw, _ = remote
    raw.outage = True
    with pytest.raises(ConnectionError):
        backend.sign_payload(b"{}", purpose=PACKAGE)
    raw.outage = False
    raw.key = Ed25519PrivateKey.generate()
    with pytest.raises(SignatureContractError, match="wrong key"):
        backend.sign_payload(b"{}", purpose=PACKAGE)


@pytest.mark.parametrize("payload", [b"not json", b'{"b":2, "a":1}', b" {}", b'{"x":1,"x":2}'])
def test_noncanonical_payloads_cannot_claim_rfc8785(remote, payload):
    backend, raw, _ = remote
    with pytest.raises(ValueError):
        backend.sign_payload(payload, purpose=PACKAGE)
    assert not raw.calls


def test_resolved_backend_outage_cannot_use_existing_local_private_key(
    finalization_source, monkeypatch
):
    key = IdentityService.get_private_key("system_id", auto_provision=False)
    remote = BoundedRemote(key)
    remote.outage = True
    monkeypatch.setattr(runtime_services, "resolve_signing_backend", lambda: remote)
    manifest = {"signing_context": {"identity_id": "system_id"}, "trace_hash": "test"}
    with pytest.raises(CertificationFailedError, match="remote unavailable"):
        CoreTraceSigner().sign(manifest, lambda item: item)
    assert "provenance_chain" not in manifest
    assert len(remote.calls) == 1


def _provision_remote_policy():
    key = IdentityService.get_private_key("system_id", auto_provision=False)
    key_id = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
    policy = SignaturePolicy("system_id", key_id, key.public_key())
    (config.TRUST_ROOT / "system_id" / "signature_policy.json").write_text(
        json.dumps(
            {
                "version": 1,
                "key_id": key_id,
                "permitted_profiles": [PROFILE, "ed25519-raw"],
                "permitted_purposes": [CERTIFICATE, PACKAGE],
                "allow_legacy_raw": True,
                "revoked": False,
            }
        )
    )
    return DigestEnvelopeSigningBackend(BoundedRemote(key), policy)


def test_full_certification_preserves_envelopes_and_verifies_without_backend(finalization_source):
    provider, scenario = finalization_source
    backend = _provision_remote_policy()
    result = execute_industrial_certification(
        "run-a", run_store=provider, scenario_data=scenario, signing_backend=backend
    )
    assert result["certified"]
    certificate = provider.get_manifest("run-a")
    assert certificate["provenance_chain"][0]["signature"]["profile"] == PROFILE
    assert certificate["verification_package"]["signature"]["profile"] == PROFILE
    assert len(backend.backend.calls) == 2
    assert all(len(payload) <= 4096 for payload in backend.backend.calls)
    backend.backend.outage = True
    assert TraceVerifier.verify_run("run-a", run_store=provider)["verified"]
    assert verify_trace_certificate(
        "run-a",
        provider.get_trace_bytes("run-a"),
        cert_data=certificate,
        scenario_data=scenario,
        trace_only=False,
    )["verified"]


def test_large_finalization_round_trip_preserves_and_verifies_envelope(finalization_source):
    provider, _ = finalization_source
    data = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    finalization = EvaluatorFinalizationRecord.parse_untrusted(data)
    finalization = replace(finalization, metadata={"large": "x" * 18000})
    key = IdentityService.get_private_key("eval_kernel", auto_provision=False)
    policy = SignaturePolicy(
        "eval_kernel", "sha256:" + fingerprint(key.public_key()), key.public_key()
    )
    remote = BoundedRemote(key)
    signed = finalization.sign(DigestEnvelopeSigningBackend(remote, policy))
    assert signed.evaluator_signature["envelope"]["purpose"] == FINALIZATION
    assert signed.verify_signature(public_key=key.public_key())
    parsed = EvaluatorFinalizationRecord.from_dict(signed.to_dict(), require_authoritative=True)
    assert parsed.evaluator_signature == signed.evaluator_signature
    assert len(remote.calls[0]) < 4096 < len(parsed.canonical_payload_bytes())


@pytest.mark.parametrize("purpose", [CERTIFICATE, PACKAGE])
@pytest.mark.parametrize("defect", ["outage", "profile", "digest", "ambiguous", "signature"])
def test_bad_structured_response_cannot_publish_or_seal(
    finalization_source, monkeypatch, purpose, defect
):
    from unittest.mock import Mock

    provider, scenario = finalization_source
    backend = _provision_remote_policy()
    original = backend.sign_payload

    def corrupt(*args, **kwargs):
        if kwargs["purpose"] == purpose and defect == "outage":
            raise ConnectionError("remote unavailable")
        response = original(*args, **kwargs)
        if kwargs["purpose"] == purpose:
            if defect == "profile":
                response["profile"] = "unsupported"
            elif defect == "digest":
                response["envelope"]["payload_digest"] = "0" * 64
            elif defect == "ambiguous":
                response["sig"] = response["signature"]
            elif defect == "signature":
                response["signature"] = base64.b64encode(b"\x00" * 64).decode()
        return response

    monkeypatch.setattr(backend, "sign_payload", corrupt)
    commit = Mock(wraps=provider.commit_certification)
    monkeypatch.setattr(provider, "commit_certification", commit)
    with pytest.raises((CertificationFailedError, ValueError, ConnectionError)):
        execute_industrial_certification(
            "run-a", run_store=provider, scenario_data=scenario, signing_backend=backend
        )
    commit.assert_not_called()
    assert provider.get_run("run-a")["lifecycle"] != "SEALED"
    assert not provider.get_manifest("run-a").get("verification_package")


def test_exact_certificate_projection_excludes_only_frozen_fields():
    certificate = {
        "execution_manifest": {"signature": "nested signed data"},
        "metadata": {"provenance_chain": "nested signed data"},
        "certification": {"stages": ["volatile"], "status": "pass"},
        "provenance_chain": [],
        "verification_package": {},
        "package_hash": "outside",
        "evaluation_hash": "outside",
        "verification_hash": "outside",
        "certificate_hash": "outside",
        "signing_context": {},
        "certification_diagnostics": {},
    }
    assert json.loads(certificate_payload_bytes(certificate)) == {
        "execution_manifest": {"signature": "nested signed data"},
        "metadata": {"provenance_chain": "nested signed data"},
        "certification": {"status": "pass"},
    }
