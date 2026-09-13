"""
agentv_runtime/manifest.py
Authoritative Execution Manifest Contract (AgentV Runtime v2.0.0).

Defines the immutable, single source of truth manifest shared across:
  - UI Execution Preflight & Preview
  - API /v1/evaluate
  - Runtime InProcessExecutionBackend
  - Verification Decision & Certificate Attestation
  - Evidence Packaging & Sealing
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from agentv_runtime.canonical import canonical_json_encode


def _canonical_json_bytes(data: Any) -> bytes:
    """Serializes data to canonical RFC 8785 JSON bytes (deterministic key ordering, UTF-8)."""
    return canonical_json_encode(data)


def compute_scenario_hash(scenario_data: Mapping[str, Any]) -> str:
    """Computes a deterministic SHA3-256 hash of canonical scenario contents."""
    clean_data = dict(scenario_data)
    clean_data.pop("expected_revision_hash", None)
    clean_data.pop("path", None)
    clean_data.pop("span_context", None)
    if "metadata" in clean_data and isinstance(clean_data["metadata"], dict):
        clean_meta = dict(clean_data["metadata"])
        clean_meta.pop("content_hash", None)
        clean_meta.pop("expected_revision_hash", None)
        clean_data["metadata"] = clean_meta
    canonical_bytes = _canonical_json_bytes(clean_data)
    return f"sha3_256:{hashlib.sha3_256(canonical_bytes).hexdigest()}"


@dataclass(frozen=True)
class ExecutionManifest:
    """
    Authoritative, immutable execution specification.
    Guarantees that what was previewed in the UI, executed by the backend,
    verified by the evaluator, and sealed in the evidence package are identical.
    """

    manifest_id: str
    scenario_id: str
    scenario_version: str
    scenario_hash: str
    tenant_id: str = "default"
    workspace_id: str = "default"
    agent_config: dict[str, Any] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    created_by: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    producer_identity: str = "agentv.manifest_builder"
    producer_version: str = "2.0.0"
    parent_artifact_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.parent_artifact_refs and self.scenario_hash:
            object.__setattr__(self, "parent_artifact_refs", [self.scenario_hash])

    @property
    def content_hash(self) -> str:
        """Content-addressed hash identical to canonical manifest hash."""
        return self.compute_manifest_hash()

    def compute_content_hash(self) -> str:
        """Alias for canonical content hash computation."""
        return self.compute_manifest_hash()

    def to_dict(self) -> dict[str, Any]:
        """Converts the execution manifest to a standard JSON-serializable dictionary."""
        d = asdict(self)
        d["content_hash"] = self.compute_manifest_hash()
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExecutionManifest:
        """Constructs an immutable ExecutionManifest from a mapping."""
        scen_hash = str(data.get("scenario_hash", ""))
        parent_refs = list(data.get("parent_artifact_refs") or ([scen_hash] if scen_hash else []))
        return cls(
            manifest_id=str(data.get("manifest_id", "")),
            scenario_id=str(data.get("scenario_id", "")),
            scenario_version=str(data.get("scenario_version", "1.0.0")),
            scenario_hash=scen_hash,
            tenant_id=str(data.get("tenant_id", "default")),
            workspace_id=str(data.get("workspace_id", "default")),
            agent_config=dict(data.get("agent_config") or {}),
            runtime_config=dict(data.get("runtime_config") or {}),
            environment=dict(data.get("environment") or {}),
            created_at=str(data.get("created_at") or datetime.now(UTC).isoformat()),
            created_by=str(data.get("created_by", "system")),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version", "2.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.manifest_builder")),
            producer_version=str(data.get("producer_version", "2.0.0")),
            parent_artifact_refs=parent_refs,
        )

    def compute_manifest_hash(self) -> str:
        """Computes a deterministic cryptographic hash of the canonical manifest payload."""
        data = {
            "agent_config": self.agent_config,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "environment": self.environment,
            "manifest_id": self.manifest_id,
            "metadata": self.metadata,
            "parent_artifact_refs": sorted(self.parent_artifact_refs),
            "producer_identity": self.producer_identity,
            "producer_version": self.producer_version,
            "runtime_config": self.runtime_config,
            "scenario_hash": self.scenario_hash,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(data)).hexdigest()}"


class ManifestBuilder:
    """Builder utility for creating canonical ExecutionManifest instances."""

    @staticmethod
    def build(
        scenario_data: Mapping[str, Any],
        agent_config: Mapping[str, Any] | None = None,
        runtime_config: Mapping[str, Any] | None = None,
        tenant_id: str = "default",
        workspace_id: str = "default",
        created_by: str = "system",
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionManifest:
        meta = dict(scenario_data.get("metadata") or {})
        scen_id = meta.get("id") or str(scenario_data.get("id", "unnamed_scenario"))
        scen_version = str(meta.get("version") or scenario_data.get("version", "1.0.0"))
        scen_hash = compute_scenario_hash(scenario_data)

        env = {
            "platform": sys.platform,
            "python_version": platform.python_version(),
            "hostname": platform.node() or "localhost",
            "pid": os.getpid(),
        }

        # Deterministic Manifest ID derived from scenario hash, agent config, and timestamp
        agent_dict = dict(agent_config or {})
        runtime_dict = dict(runtime_config or {})
        now_iso = datetime.now(UTC).isoformat()
        agent_hex = _canonical_json_bytes(agent_dict).hex()
        seed = f"{tenant_id}:{workspace_id}:{scen_hash}:{agent_hex}:{now_iso}"
        manifest_id = f"man_{hashlib.sha3_256(seed.encode('utf-8')).hexdigest()[:16]}"

        return ExecutionManifest(
            manifest_id=manifest_id,
            scenario_id=scen_id,
            scenario_version=scen_version,
            scenario_hash=scen_hash,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_config=agent_dict,
            runtime_config=runtime_dict,
            environment=env,
            created_at=now_iso,
            created_by=created_by,
            metadata=dict(metadata or {}),
        )


__all__ = [
    "ExecutionManifest",
    "ManifestBuilder",
    "compute_scenario_hash",
]
