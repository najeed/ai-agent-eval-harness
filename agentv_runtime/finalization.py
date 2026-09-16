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
    evaluator_signature: str = ""
    schema_version: str = FINALIZATION_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def signature(self) -> str:
        """Convenience alias for evaluator_signature."""
        return self.evaluator_signature

    def to_dict(self) -> dict[str, Any]:
        """Converts the record to a standard JSON-serializable dictionary."""
        data = asdict(self)
        computed_hash = self.compute_finalization_hash()
        data["finalization_hash"] = self.finalization_hash or computed_hash
        data["evaluator_signature"] = self.evaluator_signature
        data["manifest_hash"] = self.execution_manifest_hash
        return data

    @classmethod
    def parse_untrusted(
        cls, data: Mapping[str, Any], strict: bool = True
    ) -> EvaluatorFinalizationRecord:
        """
        Parses untrusted dictionary data into an EvaluatorFinalizationRecord.
        When strict=True, all 12 schema fields are validated
        and finalization_hash parity is enforced,
        but cryptographic signature verification against an external trust root is NOT performed.
        To verify cryptographic authenticity,
        call record.verify_authoritative(public_key, trust_root).
        """
        if strict:
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

            claimed_sig = data.get("evaluator_signature") or data.get("signature")
            if not claimed_sig or not isinstance(claimed_sig, str) or not str(claimed_sig).strip():
                raise ValueError(
                    "Missing mandatory finalization trust field 'evaluator_signature' "
                    "in EvaluatorFinalizationRecord (must be signed by authoritative evaluator)."
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
                evaluator_signature=str(claimed_sig).strip(),
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
            evaluator_signature=str(data.get("evaluator_signature") or data.get("signature") or ""),
            schema_version=str(data.get("schema_version") or FINALIZATION_SCHEMA_VERSION),
            metadata=dict(data.get("metadata") or {}),
        )

    def verify_authoritative(self, public_key: Any = None, trust_root: Any = None) -> bool:
        """Alias for verify_signature that cryptographically validates external trust."""
        return self.verify_signature(public_key=public_key, trust_root=trust_root)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        require_authoritative: bool = True,
        *,
        trust_root: Any = None,
        public_key: Any = None,
    ) -> EvaluatorFinalizationRecord:
        """
        Constructs an EvaluatorFinalizationRecord from a dictionary.
        When require_authoritative=True, strict field and hash validation is performed.
        If trust_root or public_key is provided,
        cryptographic verification against that root is required.
        """
        record = cls.parse_untrusted(data, strict=require_authoritative)
        if require_authoritative and (trust_root is not None or public_key is not None):
            if not record.verify_authoritative(public_key=public_key, trust_root=trust_root):
                raise ValueError(
                    f"EvaluatorSignatureVerificationFailed: signature for "
                    f"'{record.evaluator_identity}' could not be verified against trust root."
                )
        return record

    def canonical_payload_bytes(self) -> bytes:
        """Returns canonical RFC 8785 JSON bytes of the finalization attestation payload."""
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
        return canonical_json_encode(data)

    def compute_finalization_hash(self) -> str:
        """Computes a deterministic cryptographic hash of the canonical finalization payload."""
        return _sha3_hex(self.canonical_payload_bytes())

    def sign(self, signer: Any = None) -> EvaluatorFinalizationRecord:
        """
        Signs the canonical finalization payload with an Ed25519 private key or signer.
        If signer is None, attempts to resolve the evaluator's private key via IdentityService.
        """
        if signer is None:
            try:
                from eval_runner.identity import IdentityService

                signer = IdentityService.get_private_key(
                    self.evaluator_identity, auto_provision=True
                )
            except Exception as e:
                raise ValueError(
                    f"Could not resolve private key for '{self.evaluator_identity}': {e}"
                ) from e

        if not signer:
            raise ValueError(
                f"No private key available to sign finalization for '{self.evaluator_identity}'"
            )

        payload_bytes = self.canonical_payload_bytes()
        if hasattr(signer, "sign") and callable(signer.sign):
            sig_raw = signer.sign(payload_bytes)
        else:
            raise ValueError(f"Invalid signer object: {type(signer)}")

        sig_hex = sig_raw.hex() if isinstance(sig_raw, bytes) else str(sig_raw)
        data = asdict(self)
        data["finalization_hash"] = self.compute_finalization_hash()
        data["evaluator_signature"] = sig_hex
        return EvaluatorFinalizationRecord.from_dict(data, require_authoritative=False)

    def verify_signature(self, public_key: Any = None, trust_root: Any = None) -> bool:
        """
        Verifies evaluator_signature against an externally anchored public key.
        Accepts an Ed25519PublicKey, PEM bytes/str, or resolves from IdentityService/trust_root.
        """
        if not self.evaluator_signature:
            return False

        try:
            sig_bytes = bytes.fromhex(self.evaluator_signature)
        except Exception:
            return False

        if public_key is None:
            try:
                from pathlib import Path

                if trust_root and isinstance(trust_root, (str, Path)):
                    key_file = Path(trust_root) / self.evaluator_identity / "public_key.pem"
                    if key_file.is_file():
                        from cryptography.hazmat.primitives import serialization

                        public_key = serialization.load_pem_public_key(key_file.read_bytes())
                if public_key is None:
                    from eval_runner.identity import IdentityService

                    public_key = IdentityService.get_public_key(
                        self.evaluator_identity, auto_provision=False
                    )
            except Exception:
                public_key = None

        if not public_key:
            return False

        payload_bytes = self.canonical_payload_bytes()
        try:
            if hasattr(public_key, "verify") and callable(public_key.verify):
                public_key.verify(sig_bytes, payload_bytes)
                return True
            from cryptography.hazmat.primitives import serialization

            raw_pem = public_key.encode("utf-8") if isinstance(public_key, str) else public_key
            pk = serialization.load_pem_public_key(raw_pem)
            pk.verify(sig_bytes, payload_bytes)
            return True
        except Exception:
            return False


__all__ = [
    "EvaluatorFinalizationRecord",
    "FINALIZATION_SCHEMA_VERSION",
]
