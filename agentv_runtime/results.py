"""
agentv_runtime.results
Authoritative Product Result Contracts & Verification Schemas (v2.0.0).

First-class immutable dataclasses representing:
  - ExecutionResult: Granular turn/attempt execution details
  - EvaluationResult: Multi-attempt aggregate evaluation result
  - VerificationResult: NIST AI-100-1 7-dimension verification scoring
  - Attestation / VerificationCertificate: Cryptographically signed manifest & certificate
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


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

    def __getitem__(self, index: Any) -> Any:
        return self.attempts_results[index]

    def __len__(self) -> int:
        return len(self.attempts_results)

    def __iter__(self):
        return iter(self.attempts_results)

    def to_dict(self) -> dict[str, Any]:
        """Serializes EvaluationResult to a dictionary."""
        return asdict(self)

    def to_list(self) -> list[list[dict[str, Any]]]:
        """Returns the raw attempts list for legacy consumers."""
        return list(self.attempts_results)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationResult:
        """Constructs EvaluationResult from dictionary representation."""
        return cls(
            run_id=str(data.get("run_id", "")),
            scenario_id=str(data.get("scenario_id", "")),
            pass_at_k=float(data.get("pass_at_k", 0.0)),
            successful_attempts=int(data.get("successful_attempts", 0)),
            total_attempts=int(data.get("total_attempts", len(data.get("attempts_results", [])))),
            attempts_results=list(data.get("attempts_results", data.get("results", []))),
            metadata=dict(data.get("metadata", {})),
            config_hash=str(data.get("config_hash", "")),
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
            version=str(data.get("version", "2.0.0")),
            statistics=dict(data.get("statistics", {})),
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

    def __post_init__(self):
        if self.aggregate_score is None:
            score = self._calculate_wsm_score()
            object.__setattr__(self, "aggregate_score", score)

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
        }


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Backwards compatibility alias
VerificationCertificate = Attestation

__all__ = [
    "ExecutionResult",
    "EvaluationResult",
    "VerificationResult",
    "Attestation",
    "VerificationCertificate",
]
