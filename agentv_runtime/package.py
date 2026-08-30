"""
Canonical VerificationPackage contract.

Provides the single immutable, cryptographically sealed verification container
that binds scenario revision, resolved manifest, execution identity,
trace seal, evidence graph root, oracle inventory, and final verification decision
into one signed canonical root hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

PACKAGE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class VerificationPackage:
    """
    The authoritative, immutable verification attestation container for certified evaluation runs.
    Every 'Certified / Attested' claim must be derived from an instance of this package envelope.
    """

    scenario_id: str
    scenario_version: str
    scenario_hash: str
    manifest_id: str
    manifest_hash: str
    execution_identity: dict[str, Any]
    trace_hash: str
    trace_seal: dict[str, Any]
    evidence_root_hash: str
    required_oracle_ids: list[str]
    executed_oracle_results: list[dict[str, Any]]
    decision: dict[str, Any]
    package_version: str = PACKAGE_SCHEMA_VERSION
    package_id: str = ""
    signature: str | None = None
    signer_identity: str | None = None
    public_key_pem: str | None = None
    algorithm: str = "ed25519"
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_payload_dict(self) -> dict[str, Any]:
        """Returns the canonical deterministic dictionary of the attestation payload."""
        return {
            "decision": self.decision,
            "evidence_root_hash": self.evidence_root_hash,
            "executed_oracle_results": self.executed_oracle_results,
            "execution_identity": self.execution_identity,
            "manifest_hash": self.manifest_hash,
            "manifest_id": self.manifest_id,
            "metadata": self.metadata,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "required_oracle_ids": sorted(self.required_oracle_ids),
            "scenario_hash": self.scenario_hash,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "trace_hash": self.trace_hash,
            "trace_seal": self.trace_seal,
        }

    def canonical_payload_bytes(self) -> bytes:
        """Returns canonical UTF-8 bytes of the sorted, compact JSON payload."""
        return json.dumps(
            self.canonical_payload_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def compute_package_hash(self) -> str:
        """
        Computes a deterministic cryptographic hash (SHA3-256) of the canonical
        package payload, excluding mutable signature envelopes.
        """
        return hashlib.sha3_256(self.canonical_payload_bytes()).hexdigest()

    def sign(self, signer: Any) -> VerificationPackage:
        """
        Produces a new VerificationPackage signed with the given signer instance.
        """
        payload_bytes = self.canonical_payload_bytes()
        sig_raw = signer.sign(payload_bytes)
        sig_hex = sig_raw.hex() if isinstance(sig_raw, bytes) else str(sig_raw)
        signer_id = getattr(signer, "identity", "unknown-signer")
        algo = getattr(signer, "algorithm", "ed25519")
        pub_key = getattr(signer, "public_key_pem", None)

        data = asdict(self)
        data["signature"] = sig_hex
        data["signer_identity"] = signer_id
        data["public_key_pem"] = pub_key
        data["algorithm"] = algo
        return VerificationPackage.from_dict(data)

    def verify_signature(self, public_key_pem: str | None = None) -> bool:
        """
        Verifies the detached cryptographic signature using pure public key verification.
        Does not require possession of any private key.
        """
        if not self.signature:
            return False

        key_pem = public_key_pem or self.public_key_pem
        if not key_pem:
            return False

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            pub_key = serialization.load_pem_public_key(key_pem.encode("utf-8"))
            if isinstance(pub_key, Ed25519PublicKey):
                sig_bytes = bytes.fromhex(self.signature)
                pub_key.verify(sig_bytes, self.canonical_payload_bytes())
                return True
        except Exception:
            return False

        return False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["package_hash"] = self.compute_package_hash()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], strict: bool = False) -> VerificationPackage:
        scenario_id = str(data.get("scenario_id") or "")
        trace_hash = str(data.get("trace_hash") or "")
        if strict and (not scenario_id or not trace_hash):
            raise ValueError(
                "VerificationPackage strict instantiation requires valid "
                "scenario_id and trace_hash."
            )

        sig_raw = data.get("signature")
        if isinstance(sig_raw, dict):
            sig_val = sig_raw.get("signature")
            signer_id = sig_raw.get("identity") or data.get("signer_identity")
            pub_pem = sig_raw.get("public_key_pem") or data.get("public_key_pem")
            algo = sig_raw.get("algorithm") or data.get("algorithm", "ed25519")
        else:
            sig_val = sig_raw
            signer_id = data.get("signer_identity")
            pub_pem = data.get("public_key_pem")
            algo = data.get("algorithm", "ed25519")

        fields = {
            "scenario_id": scenario_id,
            "scenario_version": str(data.get("scenario_version") or "1.0.0"),
            "scenario_hash": str(data.get("scenario_hash") or ""),
            "manifest_id": str(data.get("manifest_id") or ""),
            "manifest_hash": str(data.get("manifest_hash") or ""),
            "execution_identity": dict(data.get("execution_identity") or {}),
            "trace_hash": trace_hash,
            "trace_seal": dict(data.get("trace_seal") or {}),
            "evidence_root_hash": str(data.get("evidence_root_hash") or ""),
            "required_oracle_ids": list(data.get("required_oracle_ids") or []),
            "executed_oracle_results": list(data.get("executed_oracle_results") or []),
            "decision": dict(data.get("decision") or {}),
            "package_version": str(data.get("package_version") or PACKAGE_SCHEMA_VERSION),
            "package_id": str(data.get("package_id") or ""),
            "signature": sig_val,
            "signer_identity": signer_id,
            "public_key_pem": pub_pem,
            "algorithm": algo,
            "metadata": dict(data.get("metadata") or {}),
        }
        return cls(**fields)
