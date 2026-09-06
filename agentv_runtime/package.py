"""
Canonical VerificationPackage contract.

Provides the single immutable, cryptographically sealed verification container
that binds scenario revision, resolved manifest, execution identity,
trace seal, evidence graph root, oracle inventory, and final verification decision
into one signed canonical root hash.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentv_runtime.canonical import canonical_json_encode

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
    key_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def canonical_payload_dict(self) -> dict[str, Any]:
        """Returns the canonical deterministic dictionary of the attestation payload."""
        return {
            "algorithm": self.algorithm,
            "decision": self.decision,
            "evidence_root_hash": self.evidence_root_hash,
            "executed_oracle_results": self.executed_oracle_results,
            "execution_identity": self.execution_identity,
            "key_id": self.key_id or "",
            "manifest_hash": self.manifest_hash,
            "manifest_id": self.manifest_id,
            "metadata": self.metadata,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "required_oracle_ids": sorted(self.required_oracle_ids),
            "scenario_hash": self.scenario_hash,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "signer_identity": self.signer_identity or "",
            "trace_hash": self.trace_hash,
            "trace_seal": self.trace_seal,
        }

    def canonical_payload_bytes(self) -> bytes:
        """Returns canonical RFC 8785 UTF-8 bytes of the sorted, compact JSON payload."""
        return canonical_json_encode(self.canonical_payload_dict())

    def compute_package_hash(self) -> str:
        """
        Computes a deterministic cryptographic hash (SHA3-256) of the canonical
        package payload, excluding mutable signature envelopes.
        """
        return hashlib.sha3_256(self.canonical_payload_bytes()).hexdigest()

    def sign(self, signer: Any) -> VerificationPackage:
        """
        Produces a new VerificationPackage signed with the given signer instance.
        Binds signer_identity, algorithm, and key_id directly to the signed attestation payload.
        """
        signer_id = getattr(signer, "identity", None) or self.signer_identity or "unknown-signer"
        algo = getattr(signer, "algorithm", None) or self.algorithm or "ed25519"
        key_id = getattr(signer, "key_id", None) or self.key_id or ""
        pub_key = getattr(signer, "public_key_pem", None) or self.public_key_pem

        presigned = VerificationPackage(
            scenario_id=self.scenario_id,
            scenario_version=self.scenario_version,
            scenario_hash=self.scenario_hash,
            manifest_id=self.manifest_id,
            manifest_hash=self.manifest_hash,
            execution_identity=self.execution_identity,
            trace_hash=self.trace_hash,
            trace_seal=self.trace_seal,
            evidence_root_hash=self.evidence_root_hash,
            required_oracle_ids=self.required_oracle_ids,
            executed_oracle_results=self.executed_oracle_results,
            decision=self.decision,
            package_version=self.package_version,
            package_id=self.package_id,
            signer_identity=signer_id,
            algorithm=algo,
            key_id=key_id,
            public_key_pem=pub_key,
            metadata=self.metadata,
        )

        payload_bytes = presigned.canonical_payload_bytes()
        sig_raw = signer.sign(payload_bytes)
        sig_hex = sig_raw.hex() if isinstance(sig_raw, bytes) else str(sig_raw)

        data = asdict(presigned)
        data["signature"] = sig_hex
        return VerificationPackage.from_dict(data)

    def verify_signature(
        self,
        public_key_pem: str | None = None,
        trust_root: Any | None = None,
        key_registry: Mapping[str, str] | None = None,
    ) -> bool:
        """
        Verifies the detached cryptographic signature against an externally anchored trust root.

        CRITICAL ZERO-TRUST RULE (Defect 1):
        An embedded public key (self.public_key_pem) is informational only and MUST NEVER
        serve as its own trust anchor. Verification REQUIRES an external trust anchor supplied via:
          1. Explicit `public_key_pem` parameter.
          2. `key_registry` mapping key_id/identity -> PEM.
          3. `trust_root` directory or resolver with .get_public_key().
          4. Global IdentityService trust root (if available).

        If an external key is resolved, and self.public_key_pem is present, they MUST match.
        If no external trust anchor is available, verification fails closed (False).
        """
        if not self.signature:
            return False

        anchored_pem: str | None = None

        if public_key_pem:
            anchored_pem = public_key_pem
        elif key_registry is not None:
            if self.key_id and self.key_id in key_registry:
                anchored_pem = key_registry[self.key_id]
            elif self.signer_identity and self.signer_identity in key_registry:
                anchored_pem = key_registry[self.signer_identity]
        elif trust_root is not None:
            if hasattr(trust_root, "get_public_key"):
                target_id = self.key_id or self.signer_identity or "system_id"
                try:
                    pk = trust_root.get_public_key(target_id)
                    if pk:
                        from cryptography.hazmat.primitives import serialization

                        anchored_pem = pk.public_bytes(
                            encoding=serialization.Encoding.PEM,
                            format=serialization.PublicFormat.SubjectPublicKeyInfo,
                        ).decode("utf-8")
                except Exception:
                    anchored_pem = None
            elif isinstance(trust_root, (str, Path)):
                root_path = Path(trust_root)
                target_id = self.key_id or self.signer_identity
                if target_id:
                    candidate = root_path / target_id / "public_key.pem"
                    if candidate.is_file():
                        anchored_pem = candidate.read_text(encoding="utf-8")
        else:
            # Check default IdentityService trust root
            try:
                from eval_runner.identity import IdentityService

                target_id = self.key_id or self.signer_identity or "system_id"
                pk = IdentityService.get_public_key(target_id, auto_provision=False)
                if pk:
                    from cryptography.hazmat.primitives import serialization

                    anchored_pem = pk.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    ).decode("utf-8")
            except Exception:
                anchored_pem = None

        # Fail closed: No external trust anchor means UNVERIFIED
        if not anchored_pem:
            return False

        # Informational key check: if embedded key exists, it must match external trust anchor
        if self.public_key_pem:
            try:
                from cryptography.hazmat.primitives import serialization

                k_embedded = serialization.load_pem_public_key(self.public_key_pem.encode("utf-8"))
                k_anchored = serialization.load_pem_public_key(anchored_pem.encode("utf-8"))
                if k_embedded.public_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                ) != k_anchored.public_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                ):
                    return False
            except Exception:
                return False

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            pub_key = serialization.load_pem_public_key(anchored_pem.encode("utf-8"))
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
            key_id = sig_raw.get("key_id") or data.get("key_id")
        else:
            sig_val = sig_raw
            signer_id = data.get("signer_identity")
            pub_pem = data.get("public_key_pem")
            algo = data.get("algorithm", "ed25519")
            key_id = data.get("key_id")

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
            "key_id": key_id,
            "metadata": dict(data.get("metadata") or {}),
        }
        return cls(**fields)
