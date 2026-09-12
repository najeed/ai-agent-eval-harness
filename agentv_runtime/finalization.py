"""
agentv_runtime.finalization — Evaluator Finalization Record Contract (AgentV v2.0.0).

Defines the immutable attestation emitted strictly by the trusted evaluator at run termination.
Certification consumes this record to attest an already-established, evaluator-verified result
bound to the execution manifest, scenario definition, evaluator configuration, required oracle set,
and evidence graph root, rather than manufacturing trust from loose trace events.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from agentv_runtime.canonical import canonical_json_encode

FINALIZATION_SCHEMA_VERSION = "1.0.0"


def _sha3_hex(data: bytes) -> str:
    return f"sha3_256:{hashlib.sha3_256(data).hexdigest()}"


@dataclass(frozen=True)
class EvaluatorFinalizationRecord:
    """
    Immutable evaluation finalization record.
    Produced exclusively by the evaluator upon completing workflow execution
    and oracle adjudication.
    """

    finalization_id: str
    run_id: str
    execution_manifest_hash: str
    scenario_id: str
    scenario_version: str
    scenario_hash: str
    evaluator_identity: str
    evaluator_config_hash: str
    required_oracle_ids: list[str]
    evidence_root_hash: str
    outcome: str  # "pass" | "fail"
    score: float
    finalized_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    terminal_seq: int = 0
    schema_version: str = FINALIZATION_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converts the record to a standard JSON-serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvaluatorFinalizationRecord:
        """Constructs an EvaluatorFinalizationRecord from a dictionary."""
        raw_oracles = data.get("required_oracle_ids") or []
        req_oracles = [str(o) for o in raw_oracles if o]
        return cls(
            finalization_id=str(data.get("finalization_id") or ""),
            run_id=str(data.get("run_id") or ""),
            execution_manifest_hash=str(data.get("execution_manifest_hash") or ""),
            scenario_id=str(data.get("scenario_id") or ""),
            scenario_version=str(data.get("scenario_version") or "1.0.0"),
            scenario_hash=str(data.get("scenario_hash") or ""),
            evaluator_identity=str(data.get("evaluator_identity") or "system_evaluator"),
            evaluator_config_hash=str(data.get("evaluator_config_hash") or ""),
            required_oracle_ids=req_oracles,
            evidence_root_hash=str(data.get("evidence_root_hash") or ""),
            outcome=str(data.get("outcome") or "fail").lower(),
            score=float(data.get("score") if data.get("score") is not None else 0.0),
            finalized_at=str(data.get("finalized_at") or datetime.now(UTC).isoformat()),
            terminal_seq=int(data.get("terminal_seq") or 0),
            schema_version=str(data.get("schema_version") or FINALIZATION_SCHEMA_VERSION),
            metadata=dict(data.get("metadata") or {}),
        )

    def compute_finalization_hash(self) -> str:
        """Computes a deterministic cryptographic hash of the canonical finalization payload."""
        data = {
            "finalization_id": self.finalization_id,
            "run_id": self.run_id,
            "execution_manifest_hash": self.execution_manifest_hash,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "scenario_hash": self.scenario_hash,
            "evaluator_identity": self.evaluator_identity,
            "evaluator_config_hash": self.evaluator_config_hash,
            "required_oracle_ids": sorted(self.required_oracle_ids),
            "evidence_root_hash": self.evidence_root_hash,
            "outcome": self.outcome,
            "score": self.score,
            "finalized_at": self.finalized_at,
            "terminal_seq": self.terminal_seq,
            "schema_version": self.schema_version,
            "metadata": self.metadata,
        }
        return _sha3_hex(canonical_json_encode(data))


__all__ = [
    "EvaluatorFinalizationRecord",
    "FINALIZATION_SCHEMA_VERSION",
]
