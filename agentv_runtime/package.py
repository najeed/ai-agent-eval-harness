"""
Canonical VerificationPackage contract (Phase-0 P0-8).

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
    The authoritative, immutable verification container for certified evaluation runs.
    Every 'Certified / Attested' claim must be derived from an instance of this package.
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
    algorithm: str | None = "ed25519"
    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_package_hash(self) -> str:
        """
        Computes a deterministic cryptographic hash (SHA3-256) of the canonical
        package payload, excluding mutable signature envelopes.
        """
        payload = {
            "package_version": self.package_version,
            "package_id": self.package_id,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "scenario_hash": self.scenario_hash,
            "manifest_id": self.manifest_id,
            "manifest_hash": self.manifest_hash,
            "execution_identity": self.execution_identity,
            "trace_hash": self.trace_hash,
            "trace_seal": self.trace_seal,
            "evidence_root_hash": self.evidence_root_hash,
            "required_oracle_ids": sorted(self.required_oracle_ids),
            "executed_oracle_results": self.executed_oracle_results,
            "decision": self.decision,
            "metadata": self.metadata,
        }
        canonical_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha3_256(canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["package_hash"] = self.compute_package_hash()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationPackage:
        fields = {
            "scenario_id": str(data.get("scenario_id") or ""),
            "scenario_version": str(data.get("scenario_version") or "1.0.0"),
            "scenario_hash": str(data.get("scenario_hash") or ""),
            "manifest_id": str(data.get("manifest_id") or ""),
            "manifest_hash": str(data.get("manifest_hash") or ""),
            "execution_identity": dict(data.get("execution_identity") or {}),
            "trace_hash": str(data.get("trace_hash") or ""),
            "trace_seal": dict(data.get("trace_seal") or {}),
            "evidence_root_hash": str(data.get("evidence_root_hash") or ""),
            "required_oracle_ids": list(data.get("required_oracle_ids") or []),
            "executed_oracle_results": list(data.get("executed_oracle_results") or []),
            "decision": dict(data.get("decision") or {}),
            "package_version": str(data.get("package_version") or PACKAGE_SCHEMA_VERSION),
            "package_id": str(data.get("package_id") or ""),
            "signature": data.get("signature"),
            "signer_identity": data.get("signer_identity"),
            "algorithm": data.get("algorithm", "ed25519"),
            "metadata": dict(data.get("metadata") or {}),
        }
        return cls(**fields)
