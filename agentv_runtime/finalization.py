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
    finalization_hash: str = ""
    schema_version: str = FINALIZATION_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converts the record to a standard JSON-serializable dictionary."""
        data = asdict(self)
        computed_hash = self.compute_finalization_hash()
        data["finalization_hash"] = self.finalization_hash or computed_hash
        data["manifest_hash"] = self.execution_manifest_hash
        return data

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], require_authoritative: bool = True
    ) -> EvaluatorFinalizationRecord:
        """
        Constructs an EvaluatorFinalizationRecord from a dictionary.
        When require_authoritative is True (default), all 12 trust fields are mandatory
        and zero defaulting is permitted.
        """
        if require_authoritative:
            mandatory_str_fields = [
                ("finalization_id", "finalization_id"),
                ("run_id", "run_id"),
                ("scenario_id", "scenario_id"),
                ("scenario_version", "scenario_version"),
                ("scenario_hash", "scenario_hash"),
                ("evaluator_identity", "evaluator_identity"),
                ("evaluator_config_hash", "evaluator_config_hash"),
                ("evidence_root_hash", "evidence_root_hash"),
            ]
            for key, display_name in mandatory_str_fields:
                val = data.get(key)
                if not val or not isinstance(val, str) or not str(val).strip():
                    raise ValueError(
                        f"Missing mandatory finalization trust field '{display_name}' "
                        "in EvaluatorFinalizationRecord (no defaulting permitted)."
                    )

            manifest_h = data.get("execution_manifest_hash") or data.get("manifest_hash")
            if not manifest_h or not isinstance(manifest_h, str) or not str(manifest_h).strip():
                raise ValueError(
                    "Missing mandatory finalization trust field 'execution_manifest_hash' / "
                    "'manifest_hash' in EvaluatorFinalizationRecord."
                )

            raw_oracles = data.get("required_oracle_ids")
            if raw_oracles is None or not isinstance(raw_oracles, list):
                raise ValueError(
                    "Missing mandatory finalization trust field 'required_oracle_ids' "
                    "in EvaluatorFinalizationRecord (must be a list)."
                )

            term_seq = data.get("terminal_seq")
            if term_seq is None or not isinstance(term_seq, int):
                raise ValueError(
                    "Missing mandatory finalization trust field 'terminal_seq' "
                    "in EvaluatorFinalizationRecord (must be an integer)."
                )

            outcome_val = data.get("outcome")
            if not outcome_val or str(outcome_val).strip().lower() not in ("pass", "fail"):
                raise ValueError(
                    "Missing or invalid mandatory finalization outcome ('pass' | 'fail') "
                    "in EvaluatorFinalizationRecord."
                )

            score_val = data.get("score")
            if score_val is None or not isinstance(score_val, (int, float)):
                raise ValueError(
                    "Missing mandatory finalization trust field 'score' "
                    "in EvaluatorFinalizationRecord (must be a float/int)."
                )

            claimed_hash = data.get("finalization_hash")
            if (
                not claimed_hash
                or not isinstance(claimed_hash, str)
                or not str(claimed_hash).strip()
            ):
                raise ValueError(
                    "Missing mandatory 'finalization_hash' in EvaluatorFinalizationRecord."
                )

            req_oracles = [str(o) for o in raw_oracles if o]
            record = cls(
                finalization_id=str(data["finalization_id"]).strip(),
                run_id=str(data["run_id"]).strip(),
                execution_manifest_hash=str(manifest_h).strip(),
                scenario_id=str(data["scenario_id"]).strip(),
                scenario_version=str(data["scenario_version"]).strip(),
                scenario_hash=str(data["scenario_hash"]).strip(),
                evaluator_identity=str(data["evaluator_identity"]).strip(),
                evaluator_config_hash=str(data["evaluator_config_hash"]).strip(),
                required_oracle_ids=req_oracles,
                evidence_root_hash=str(data["evidence_root_hash"]).strip(),
                outcome=str(outcome_val).strip().lower(),
                score=float(score_val),
                finalized_at=str(data.get("finalized_at") or datetime.now(UTC).isoformat()),
                terminal_seq=int(term_seq),
                finalization_hash=str(claimed_hash).strip(),
                schema_version=str(data.get("schema_version") or FINALIZATION_SCHEMA_VERSION),
                metadata=dict(data.get("metadata") or {}),
            )

            computed_hash = record.compute_finalization_hash()
            if claimed_hash != computed_hash:
                raise ValueError(
                    f"FinalizationHashMismatch: claimed '{claimed_hash}' "
                    f"does not match computed hash '{computed_hash}'"
                )
            return record

        # Non-authoritative permissive mode (for drafts / preflight inspection only)
        raw_oracles = data.get("required_oracle_ids") or []
        req_oracles = [str(o) for o in raw_oracles if o]
        m_hash = str(data.get("execution_manifest_hash") or data.get("manifest_hash") or "")
        return cls(
            finalization_id=str(data.get("finalization_id") or ""),
            run_id=str(data.get("run_id") or ""),
            execution_manifest_hash=m_hash,
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
            finalization_hash=str(data.get("finalization_hash") or ""),
            schema_version=str(data.get("schema_version") or FINALIZATION_SCHEMA_VERSION),
            metadata=dict(data.get("metadata") or {}),
        )

    def compute_finalization_hash(self) -> str:
        """Computes a deterministic cryptographic hash of the canonical finalization payload."""
        data = {
            "evaluator_config_hash": self.evaluator_config_hash,
            "evaluator_identity": self.evaluator_identity,
            "evidence_root_hash": self.evidence_root_hash,
            "execution_manifest_hash": self.execution_manifest_hash,
            "finalization_id": self.finalization_id,
            "finalized_at": self.finalized_at,
            "metadata": self.metadata,
            "outcome": self.outcome,
            "required_oracle_ids": sorted(self.required_oracle_ids),
            "run_id": self.run_id,
            "scenario_hash": self.scenario_hash,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "schema_version": self.schema_version,
            "score": self.score,
            "terminal_seq": self.terminal_seq,
        }
        return _sha3_hex(canonical_json_encode(data))


__all__ = [
    "EvaluatorFinalizationRecord",
    "FINALIZATION_SCHEMA_VERSION",
]
