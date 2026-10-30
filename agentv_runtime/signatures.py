"""Versioned signatures over digest envelopes, with offline trust-policy verification.

This profile uses ordinary Ed25519 on RFC 8785 envelope bytes, not Ed25519ph.
Payload projection is performed by the artifact owner before calling this module.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.interfaces import SigningBackend

PROFILE = "agentv.signature.digest-envelope.v1"
CERTIFICATE = "agentv.certificate"
PACKAGE = "agentv.verification-package"
FINALIZATION = "agentv.evaluator-finalization"
PROJECTIONS = {
    CERTIFICATE: "agentv.certificate.unsigned.v1",
    PACKAGE: "agentv.verification-package.unsigned.v1",
    FINALIZATION: "agentv.evaluator-finalization.unsigned.v1",
}
MAX_ENVELOPE_BYTES = 4096

# These are protocol constants. Changing them requires a new projection/profile version.
CERTIFICATE_EXCLUDED_FIELDS = frozenset(
    {
        "provenance_chain",
        "signing_context",
        "certification_diagnostics",
        "verification_package",
        "package_hash",
        "evaluation_hash",
        "verification_hash",
        "certificate_hash",
    }
)
PACKAGE_UNSIGNED_FIELDS = frozenset(
    {
        "algorithm",
        "certificate_hash",
        "decision",
        "evaluation_hash",
        "evidence_root_hash",
        "executed_oracle_results",
        "execution_identity",
        "finalization_hash",
        "key_id",
        "manifest_hash",
        "manifest_id",
        "metadata",
        "package_id",
        "package_version",
        "parent_artifact_refs",
        "producer_identity",
        "producer_version",
        "required_oracle_ids",
        "scenario_hash",
        "scenario_id",
        "scenario_version",
        "schema_version",
        "signer_identity",
        "trace_hash",
        "trace_seal",
        "verification_hash",
    }
)
FINALIZATION_UNSIGNED_FIELDS = frozenset(
    {
        "evaluator_config_hash",
        "evaluator_identity",
        "evidence_root_hash",
        "execution_manifest_hash",
        "finalization_id",
        "finalized_at",
        "metadata",
        "outcome",
        "required_oracle_ids",
        "run_id",
        "scenario_hash",
        "scenario_id",
        "scenario_version",
        "schema_version",
        "score",
        "terminal_seq",
    }
)


def certificate_payload_bytes(certificate: dict[str, Any]) -> bytes:
    """certificate.unsigned.v1: retain all other fields, including execution_manifest.

    Only the listed top-level fields and certification.stages are excluded. No
    recursive deletion, metadata filtering, or speculative legacy projections.
    """
    projected = {k: v for k, v in certificate.items() if k not in CERTIFICATE_EXCLUDED_FIELDS}
    if isinstance(projected.get("certification"), dict):
        projected["certification"] = {
            k: v for k, v in projected["certification"].items() if k != "stages"
        }
    return canonical_json_encode(projected)


class SignatureContractError(ValueError):
    """The signer response or trusted signature policy does not satisfy the profile."""


def canonical_payload_from_json(raw: bytes) -> bytes:
    """Strict JSON transport decoding: duplicate keys and non-I-JSON inputs fail."""
    if not isinstance(raw, bytes):
        raise SignatureContractError("JSON transport input must be UTF-8 bytes")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SignatureContractError("Duplicate JSON key in signed artifact")
            result[key] = value
        return result

    def constant(value):
        raise SignatureContractError(f"Non-finite JSON constant: {value}")

    def integer(token):
        value = int(token)
        if abs(value) <= 9007199254740991:
            return value
        # JCS may serialize a finite binary64 float (e.g. 1e20) in integer
        # notation. Accept that exact value; never silently round an integer.
        binary64 = float(token)
        if int(binary64) != value:
            raise SignatureContractError("JSON integer is not exactly representable as binary64")
        return binary64

    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant, parse_int=integer
    )
    if not isinstance(value, dict):
        raise SignatureContractError("Artifact projection must be a JSON object")
    return canonical_json_encode(value)


def public_key_object(key: Any) -> Ed25519PublicKey:
    if isinstance(key, str):
        key = key.encode("utf-8")
    if isinstance(key, bytes):
        key = serialization.load_pem_public_key(key)
    if not isinstance(key, Ed25519PublicKey):
        raise SignatureContractError("Expected an externally anchored Ed25519 public key")
    return key


def fingerprint(key: Any) -> str:
    der = public_key_object(key).public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()


@dataclass(frozen=True)
class SignaturePolicy:
    """External trust-store authorization; never construct from an artifact's claims."""

    identity: str
    key_id: str
    public_key: Any
    permitted_purposes: tuple[str, ...] = field(default_factory=lambda: tuple(PROJECTIONS))
    permitted_profiles: tuple[str, ...] = (PROFILE, "ed25519-raw")
    allow_legacy_raw: bool = True
    revoked: bool = False
    not_before: datetime | None = None
    not_after: datetime | None = None

    def authorize(self, purpose: str, profile: str) -> None:
        if self.revoked or purpose not in self.permitted_purposes:
            raise SignatureContractError("Signing key is revoked or not authorized for purpose")
        if profile not in self.permitted_profiles:
            raise SignatureContractError("Signature profile is not permitted by trust policy")
        now = datetime.now(UTC)
        if (self.not_before and now < self.not_before) or (
            self.not_after and now >= self.not_after
        ):
            raise SignatureContractError("Signing key is outside its trusted validity interval")


def _immutable_key_id(policy: SignaturePolicy) -> None:
    # v1 supports content-addressed keys and immutable AWS KMS key ARNs, not aliases.
    if policy.key_id == "sha256:" + fingerprint(policy.public_key):
        return
    if re.fullmatch(r"arn:[a-z0-9-]+:kms:[a-z0-9-]+:[0-9]{12}:key/[a-zA-Z0-9-]+", policy.key_id):
        return
    raise SignatureContractError("Expected a public-key fingerprint ID or immutable KMS key ARN")


def unsigned_envelope(payload: bytes, policy: SignaturePolicy, purpose: str) -> dict[str, Any]:
    """Build all signed bindings from expected inputs, never from signer claims."""
    policy.authorize(purpose, PROFILE)
    _immutable_key_id(policy)
    if not isinstance(payload, bytes) or not policy.identity:
        raise SignatureContractError("Payload bytes and a trusted signer identity are required")
    if canonical_payload_from_json(payload) != payload:
        raise SignatureContractError("Payload projection must already be canonical RFC8785 JSON")
    envelope = {
        "profile": PROFILE,
        "version": 1,
        "envelope_canonicalization": "RFC8785",
        "purpose": purpose,
        "payload_projection": PROJECTIONS[purpose],
        "payload_canonicalization": "RFC8785",
        "payload_digest": hashlib.sha256(payload).hexdigest(),
        "payload_digest_algorithm": "sha256",
        "payload_digest_encoding": "hex-lowercase",
        "signing_algorithm": "Ed25519",
        "signing_semantics": "raw-ed25519-over-canonical-envelope-bytes",
        "signer_identity": policy.identity,
        "key_id": policy.key_id,
        "public_key_fingerprint": fingerprint(policy.public_key),
        "fingerprint_algorithm": "sha256",
        "public_key_encoding": "spki-der",
        "signature_encoding": "base64-rfc4648-padded",
        "signature_length": 64,
    }
    if len(canonical_json_encode(envelope)) > MAX_ENVELOPE_BYTES:
        raise SignatureContractError("Canonical signing envelope exceeds the RAW signer limit")
    return envelope


def verify_artifact_signature(
    payload: bytes, response: Any, policy: SignaturePolicy, purpose: str
) -> bool:
    """Offline verification; no backend calls and no rejected-envelope legacy fallback."""
    try:
        if not isinstance(response, dict):
            if not policy.allow_legacy_raw or not isinstance(response, str):
                return False
            policy.authorize(purpose, "ed25519-raw")
            if not re.fullmatch(r"[0-9a-fA-F]{128}", response):
                return False
            public_key_object(policy.public_key).verify(bytes.fromhex(response), payload)
            return True
        if set(response) != {"profile", "envelope", "signature"}:
            return False
        if response["profile"] != PROFILE:
            return False
        expected = unsigned_envelope(payload, policy, purpose)
        envelope = response["envelope"]
        # Compare canonical bytes as well as field sets: JSON true must not equal integer 1.
        if not isinstance(envelope, dict) or set(envelope) != set(expected):
            return False
        if any(type(envelope[key]) is not type(expected[key]) for key in expected):
            return False
        signed = canonical_json_encode(envelope)
        if signed != canonical_json_encode(expected):
            return False
        encoded = response["signature"]
        if not isinstance(encoded, str):
            return False
        signature = base64.b64decode(encoded, validate=True)
        if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != encoded:
            return False
        public_key_object(policy.public_key).verify(signature, signed)
        return True
    except (ValueError, TypeError, KeyError, binascii.Error, OverflowError):
        return False
    except Exception:
        # cryptography.InvalidSignature and malformed external trust material fail closed.
        return False


def resolve_policy(
    identity: str, public_key: Any = None, trust_root: Any = None
) -> SignaturePolicy:
    """Resolve policy from an external trust root; embedded fields are never consulted."""
    if hasattr(trust_root, "get_signature_policy"):
        policy = trust_root.get_signature_policy(identity)
    else:
        from pathlib import Path

        from eval_runner.identity import IdentityService

        policy = IdentityService.get_signature_policy(
            identity, public_key, trust_root if isinstance(trust_root, (str, Path)) else None
        )
    if not isinstance(policy, SignaturePolicy) or policy.identity != identity:
        raise SignatureContractError("External signature policy has a different signer identity")
    if public_key is not None and fingerprint(public_key) != fingerprint(policy.public_key):
        raise SignatureContractError("Signature policy does not match the external public key")
    return policy


def validate_signing_response(
    payload: bytes, response: Any, *, identity: str, purpose: str
) -> str | dict[str, Any]:
    """Validate provider responses before publishing them, preserving complete envelopes."""
    if isinstance(response, dict):
        # Unversioned signature/sig wrappers are ambiguous and deliberately unsupported.
        policy = resolve_policy(identity)
        if not verify_artifact_signature(payload, response, policy, purpose):
            raise SignatureContractError("Invalid or unauthorized structured signing response")
        return response
    if not isinstance(response, str) or not re.fullmatch(r"[0-9a-fA-F]{128}", response):
        raise SignatureContractError(
            "IncompleteSignature: expected Ed25519 or a versioned envelope"
        )
    return response


class DigestEnvelopeSigningBackend(SigningBackend):
    """Adapt a deliberately selected RAW backend to the public digest-envelope contract.

    For AWS the wrapped provider must call ED25519_SHA_512 with MessageType RAW.
    Remote failures propagate; this adapter has no local signer or recovery provider.
    """

    def __init__(self, backend: Any, policy: SignaturePolicy):
        self.backend = backend
        self.policy = policy
        self.identity = policy.identity
        self.key_id = policy.key_id
        self.algorithm = "ed25519"
        self.public_key_pem = (
            public_key_object(policy.public_key)
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode("ascii")
        )
        self.requires_private_key_material = getattr(
            backend, "requires_private_key_material", False
        )

    def can_sign(self) -> bool:
        return self.backend.can_sign()

    def get_public_key(self, identity: str) -> Any:
        if identity != self.policy.identity:
            raise SignatureContractError("Signer identity differs from selected key")
        return public_key_object(self.policy.public_key)

    def sign_payload(
        self, payload: bytes, key_identifier: Any = None, *, purpose: str, **kwargs: Any
    ) -> dict[str, Any]:
        envelope = unsigned_envelope(payload, self.policy, purpose)
        raw = self.backend.sign_payload(canonical_json_encode(envelope), key_identifier, **kwargs)
        if not isinstance(raw, str) or not re.fullmatch(r"[0-9a-fA-F]{128}", raw):
            raise SignatureContractError("RAW backend must return exactly 64 hex-encoded bytes")
        response = {
            "profile": PROFILE,
            "envelope": envelope,
            "signature": base64.b64encode(bytes.fromhex(raw)).decode("ascii"),
        }
        if not verify_artifact_signature(payload, response, self.policy, purpose):
            raise SignatureContractError("RAW backend returned a signature from the wrong key")
        return response

    def verify_signature(
        self, payload: bytes, signature: Any, public_key_identifier: Any = None, *, purpose: str
    ) -> bool:
        if public_key_identifier is not None and fingerprint(public_key_identifier) != fingerprint(
            self.policy.public_key
        ):
            return False
        return verify_artifact_signature(payload, signature, self.policy, purpose)
