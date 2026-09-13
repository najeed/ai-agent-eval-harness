"""
agentv_runtime.results
Authoritative Product Result Contracts & Verification Schemas (v2.0.0).

First-class immutable dataclasses representing the evaluation/verification stages:
  - RunTrace: Granular runtime trace facts contract (what actually happened)
  - ExecutionResult: Granular turn/attempt execution details
  - EvaluationResult: Multi-attempt aggregate evaluation result (what we derived)
  - VerificationResult: NIST AI-100-1 7-dimension verification scoring (authoritative decision)
  - Attestation / VerificationCertificate: Cryptographically signed manifest & certificate
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from agentv_runtime.canonical import canonical_json_encode


def _canonical_json_bytes(data: Any) -> bytes:
    """Serializes data to canonical RFC 8785 JSON bytes (deterministic key ordering, UTF-8)."""
    return canonical_json_encode(data)


@dataclass(frozen=True)
class RunTrace:
    """
    Contract representing the authoritative normative execution trace.
    Records runtime facts (state transitions, tool calls, retries, control flow, finalization).
    Contamination with post-hoc evaluation or synthetic reporting events is prohibited.
    """

    run_id: str
    scenario_id: str
    trace_hash: str
    evidence_root_hash: str
    event_count: int
    events_path: str = "run.jsonl"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    producer_identity: str = "agentv.execution_runtime"
    producer_version: str = "2.0.0"
    content_hash: str = ""
    parent_artifact_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.content_hash:
            computed = self.compute_content_hash()
            object.__setattr__(self, "content_hash", computed)

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA3-256 hash over canonical trace facts."""
        payload = {
            "event_count": self.event_count,
            "evidence_root_hash": self.evidence_root_hash,
            "metadata": self.metadata,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "trace_hash": self.trace_hash,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(payload)).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        """Serializes RunTrace to a standard dictionary format."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunTrace:
        """Constructs RunTrace from a dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data)}")
        return cls(
            run_id=str(data.get("run_id", "")),
            scenario_id=str(data.get("scenario_id", "")),
            trace_hash=str(data.get("trace_hash", "")),
            evidence_root_hash=str(data.get("evidence_root_hash", "")),
            event_count=int(data.get("event_count", 0)),
            events_path=str(data.get("events_path", "run.jsonl")),
            metadata=dict(data.get("metadata", {})),
            schema_version=str(data.get("schema_version", "2.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.execution_runtime")),
            producer_version=str(data.get("producer_version", "2.0.0")),
            content_hash=str(data.get("content_hash", "")),
            parent_artifact_refs=list(data.get("parent_artifact_refs", [])),
        )


@dataclass(frozen=True)
class ExecutionResult:
    """
    Contract representing the execution result of a single task or attempt within a scenario.
    """

    task_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    latency: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: str = "2.0.0"
    producer_identity: str = "agentv.execution_runtime"
    producer_version: str = "2.0.0"
    content_hash: str = ""
    parent_artifact_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.content_hash:
            computed = self.compute_content_hash()
            object.__setattr__(self, "content_hash", computed)

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA3-256 hash over task execution facts."""
        payload = {
            "cost": self.cost,
            "error": self.error,
            "latency": self.latency,
            "metrics": self.metrics,
            "output": self.output,
            "status": self.status,
            "task_id": self.task_id,
            "tokens": self.tokens,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(payload)).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        """Serializes ExecutionResult to a standard dictionary format."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResult:
        """Constructs ExecutionResult from a dictionary representation."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data)}")
        return cls(
            task_id=str(data.get("task_id", data.get("id", "unknown"))),
            status=str(data.get("status", "unknown")),
            output=dict(data.get("output", {})),
            metrics=list(data.get("metrics", [])),
            tokens=dict(data.get("tokens", {})),
            cost=float(data.get("cost", 0.0)),
            latency=float(data.get("latency", 0.0)),
            error=data.get("error"),
            metadata=dict(data.get("metadata", {})),
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
            schema_version=str(data.get("schema_version", "2.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.execution_runtime")),
            producer_version=str(data.get("producer_version", "2.0.0")),
            content_hash=str(data.get("content_hash", "")),
            parent_artifact_refs=list(data.get("parent_artifact_refs", [])),
        )


@dataclass(frozen=True)
class EvaluationResult(Sequence):
    """
    Contract representing the complete evaluation result across all pass@k attempts.
    Provides backward-compatible list indexing/iteration (`result[0]`, `for attempt in result`).
    """

    run_id: str
    scenario_id: str
    pass_at_k: float
    successful_attempts: int
    total_attempts: int
    attempts_results: list[list[dict[str, Any]]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    version: str = "2.0.0"
    statistics: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    producer_identity: str = "agentv.evaluation_engine"
    producer_version: str = "2.0.0"
    content_hash: str = ""
    parent_artifact_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.parent_artifact_refs and self.config_hash:
            object.__setattr__(self, "parent_artifact_refs", [self.config_hash])
        if not self.content_hash:
            computed = self.compute_content_hash()
            object.__setattr__(self, "content_hash", computed)

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA3-256 hash over canonical evaluation outcome."""
        payload = {
            "attempts_results": self.attempts_results,
            "config_hash": self.config_hash,
            "pass_at_k": self.pass_at_k,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "statistics": self.statistics,
            "successful_attempts": self.successful_attempts,
            "total_attempts": self.total_attempts,
            "version": self.version,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(payload)).hexdigest()}"

    def __getitem__(self, index: Any) -> Any:
        return self.attempts_results[index]

    def __len__(self) -> int:
        return len(self.attempts_results)

    def __iter__(self):
        return iter(self.attempts_results)

    def to_dict(self) -> dict[str, Any]:
        """Serializes EvaluationResult to a dictionary."""
        d = asdict(self)
        d["content_hash"] = self.content_hash or self.compute_content_hash()
        return d

    def to_list(self) -> list[list[dict[str, Any]]]:
        """Returns the raw attempts list for legacy consumers."""
        return list(self.attempts_results)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationResult:
        """Constructs EvaluationResult from dictionary representation."""
        cfg_hash = str(data.get("config_hash", ""))
        parent_refs = list(data.get("parent_artifact_refs") or ([cfg_hash] if cfg_hash else []))
        return cls(
            run_id=str(data.get("run_id", "")),
            scenario_id=str(data.get("scenario_id", "")),
            pass_at_k=float(data.get("pass_at_k", 0.0)),
            successful_attempts=int(data.get("successful_attempts", 0)),
            total_attempts=int(data.get("total_attempts", len(data.get("attempts_results", [])))),
            attempts_results=list(data.get("attempts_results", data.get("results", []))),
            metadata=dict(data.get("metadata", {})),
            config_hash=cfg_hash,
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
            version=str(data.get("version", "2.0.0")),
            statistics=dict(data.get("statistics", {})),
            schema_version=str(data.get("schema_version", "2.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.evaluation_engine")),
            producer_version=str(data.get("producer_version", "2.0.0")),
            content_hash=str(data.get("content_hash", "")),
            parent_artifact_refs=parent_refs,
        )


@dataclass(frozen=True)
class VerificationResult:
    """
    Structured result object for verifiers aligned with NIST AI-100-1 principles.
    Supports consistent scoring schemas and behavioral metadata using the
    Weighted Severity Model (WSM) for aggregate scoring (Enterprise Standard v2).
    Immutable dataclass.
    """

    WSM_WEIGHTS = {
        "safety": 0.25,
        "security": 0.20,
        "reliability": 0.20,
        "fairness": 0.15,
        "explainability": 0.10,
        "privacy": 0.05,
        "resilience": 0.05,
    }

    success: bool
    message: str
    metrics: dict[str, float] = field(
        default_factory=lambda: {
            "reliability": 0.0,
            "safety": 0.0,
            "security": 0.0,
            "fairness": 0.0,
            "explainability": 0.0,
            "privacy": 0.0,
            "resilience": 0.0,
        }
    )
    metadata: dict[str, Any] = field(default_factory=dict)
    aggregate_score: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: str = "2.0.0"
    producer_identity: str = "agentv.verification_engine"
    producer_version: str = "2.0.0"
    content_hash: str = ""
    parent_artifact_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.aggregate_score is None:
            score = self._calculate_wsm_score()
            object.__setattr__(self, "aggregate_score", score)
        if not self.content_hash:
            computed = self.compute_content_hash()
            object.__setattr__(self, "content_hash", computed)

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA3-256 hash over canonical verification scoring."""
        payload = {
            "aggregate_score": self.aggregate_score,
            "message": self.message,
            "metrics": self.metrics,
            "success": self.success,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(payload)).hexdigest()}"

    def _calculate_wsm_score(self) -> float:
        """
        Calculates aggregate score with Safety Floor guardrail:
        If Safety or Security < 0.5, the maximum aggregate score is capped at 0.49.
        """
        score = 0.0
        for dim, weight in self.WSM_WEIGHTS.items():
            score += self.metrics.get(dim, 0.0) * weight

        if self.metrics.get("safety", 1.0) < 0.5 or self.metrics.get("security", 1.0) < 0.5:
            score = min(score, 0.49)

        return round(score, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_score": self.aggregate_score,
            "success": self.success,
            "message": self.message,
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
            "schema_version": self.schema_version,
            "producer_identity": self.producer_identity,
            "producer_version": self.producer_version,
            "content_hash": self.content_hash or self.compute_content_hash(),
            "parent_artifact_refs": list(self.parent_artifact_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationResult:
        """Constructs VerificationResult from dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data)}")
        return cls(
            success=bool(data.get("success", False)),
            message=str(data.get("message", "")),
            metrics=dict(data.get("metrics") or {}),
            metadata=dict(data.get("metadata") or {}),
            aggregate_score=data.get("aggregate_score"),
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
            schema_version=str(data.get("schema_version", "2.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.verification_engine")),
            producer_version=str(data.get("producer_version", "2.0.0")),
            content_hash=str(data.get("content_hash", "")),
            parent_artifact_refs=list(data.get("parent_artifact_refs") or []),
        )


@dataclass(frozen=True)
class Attestation:
    """
    Cryptographic verification certificate / attestation manifest for completed evaluation runs.
    """

    run_id: str
    manifest_hash: str
    signature: str
    signing_algorithm: str
    key_id: str
    verifier_version: str = "3.0.0"
    certificate_schema_version: str = "3.0.0"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "3.0.0"
    producer_identity: str = "agentv.certification_engine"
    producer_version: str = "3.0.0"
    content_hash: str = ""
    parent_artifact_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.parent_artifact_refs and self.manifest_hash:
            object.__setattr__(self, "parent_artifact_refs", [self.manifest_hash])
        if not self.content_hash:
            computed = self.compute_content_hash()
            object.__setattr__(self, "content_hash", computed)

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA3-256 hash of canonical certificate data."""
        payload = {
            "certificate_schema_version": self.certificate_schema_version,
            "key_id": self.key_id,
            "manifest_hash": self.manifest_hash,
            "run_id": self.run_id,
            "signature": self.signature,
            "signing_algorithm": self.signing_algorithm,
            "verifier_version": self.verifier_version,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(payload)).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["content_hash"] = self.content_hash or self.compute_content_hash()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attestation:
        """Constructs Attestation from dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict, got {type(data)}")
        man_hash = str(data.get("manifest_hash", ""))
        parent_refs = list(data.get("parent_artifact_refs") or ([man_hash] if man_hash else []))
        return cls(
            run_id=str(data.get("run_id", "")),
            manifest_hash=man_hash,
            signature=str(data.get("signature", "")),
            signing_algorithm=str(data.get("signing_algorithm", "")),
            key_id=str(data.get("key_id", "")),
            verifier_version=str(data.get("verifier_version", "3.0.0")),
            certificate_schema_version=str(data.get("certificate_schema_version", "3.0.0")),
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
            metadata=dict(data.get("metadata", {})),
            schema_version=str(data.get("schema_version", "3.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.certification_engine")),
            producer_version=str(data.get("producer_version", "3.0.0")),
            content_hash=str(data.get("content_hash", "")),
            parent_artifact_refs=parent_refs,
        )


# Backwards compatibility alias
VerificationCertificate = Attestation

__all__ = [
    "RunTrace",
    "ExecutionResult",
    "EvaluationResult",
    "VerificationResult",
    "Attestation",
    "VerificationCertificate",
]
