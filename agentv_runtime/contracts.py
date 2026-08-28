"""
agentv_runtime.contracts
Canonical Phase-0 truth contracts (v1.0.0, @experimental).

Every badge, verdict, status and diagnostic statement rendered by any AgentV
surface MUST be traceable to one of these authoritative runtime objects.
UI-generated verification claims are prohibited by contract.

    compose -> execute -> evaluate -> verify -> certify
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

CONTRACTS_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Enums (string-valued for wire compatibility)
# ---------------------------------------------------------------------------


class Verdict:
    """Authoritative verification verdicts. UI must never invent others."""

    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    POLICY_BREACH = "POLICY_BREACH"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_EXECUTED = "NOT_EXECUTED"
    ERROR = "ERROR"
    EVALUATION_INVALID = "EVALUATION_INVALID"

    ALL = {
        VERIFIED,
        NOT_VERIFIED,
        POLICY_BREACH,
        INCONCLUSIVE,
        NOT_EXECUTED,
        ERROR,
        EVALUATION_INVALID,
    }


class ReadinessTier:
    """Preflight tiers: each tier implies all below it."""

    UNCONFIGURED = "UNCONFIGURED"
    CONFIGURED = "CONFIGURED"
    REACHABLE = "REACHABLE"
    EXECUTABLE = "EXECUTABLE"
    VERIFIABLE = "VERIFIABLE"

    ORDER = [UNCONFIGURED, CONFIGURED, REACHABLE, EXECUTABLE, VERIFIABLE]

    @classmethod
    def at_least(cls, actual: str, minimum: str) -> bool:
        try:
            return cls.ORDER.index(actual) >= cls.ORDER.index(minimum)
        except ValueError:
            return False


class ExecutionMode:
    """Execution truth modes. Simulation must never masquerade as live."""

    SIMULATED = "simulated"
    RECORD_REPLAY = "record_replay"
    LIVE = "live"
    HYBRID = "hybrid"

    ALL = {SIMULATED, RECORD_REPLAY, LIVE, HYBRID}


class RCAConfidence:
    CONFIRMED = "confirmed"
    SUSPECTED = "suspected"
    DETECTED = "detected"


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeHealth:
    """
    Authoritative runtime health. GUI headers may render READY only when
    status == HEALTHY and derived from this object — never unconditionally.
    """

    status: str  # HEALTHY | DEGRADED | UNREACHABLE
    mode: str  # production | demo
    execution_mode_default: str = ExecutionMode.SIMULATED
    version: str = ""
    last_heartbeat: str = field(default_factory=_now)
    dependencies: dict[str, str] = field(default_factory=dict)  # name -> HEALTHY|DEGRADED|FAILED
    signing_backend: str = "ephemeral"  # ephemeral | persistent
    details: list[str] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return self.status == "HEALTHY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssertionResult:
    """One evaluated assertion with full evidence, not a bare boolean."""

    assertion_id: str
    kind: str  # metric | state_hygiene | expected_outcome | policy
    node_id: str | None
    passed: bool
    severity: str = "required"  # required | informational
    expected: Any = None
    actual: Any = None
    actual_before: Any = None  # transition-based verification evidence
    mode: str | None = None
    reason: str | None = None
    invalid: bool = False  # EVALUATION_INVALID semantics
    source_ref: str | None = None  # trace event/artifact pointer

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransitionEvidence:
    """Executed control-flow transition: selected edge + evaluated predicate."""

    from_node: str
    to_node: str
    selected_edge_id: str
    edge_type: str
    transition_reason: str
    evaluated_predicate: dict[str, Any] | None = None
    observed_value: Any = None
    source_execution_id: str | None = None
    target_execution_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    """
    THE authoritative verification object (Phase-0 P0-2).

    A run detail view may only display claims explicitly present here.
    """

    evaluation_run_id: str
    scenario_version_id: str
    case_id: str
    attempt_id: str
    attempt_number: int
    execution_mode: str  # simulated | record_replay | live | hybrid
    verdict: str  # Verdict.*
    because: list[str] = field(default_factory=list)
    assertions: list[AssertionResult] = field(default_factory=list)
    transitions: list[TransitionEvidence] = field(default_factory=list)
    observed_execution: list[dict[str, Any]] = field(default_factory=list)
    policy_checks: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    signature_verified: bool = False
    evidence_complete: bool = False
    signer_identity: str | None = None
    manifest_digest: str | None = None
    workflow_status: str = ""  # workflow_completed | workflow_failed | workflow_aborted
    failure_policy: str = ""
    ir_version: str = ""
    statistics: dict[str, Any] = field(default_factory=dict)  # pass@k contract etc.
    timestamp: str = field(default_factory=_now)

    @property
    def is_verified(self) -> bool:
        return self.verdict == Verdict.VERIFIED

    @property
    def attestation_grade(self) -> str:
        """
        Distinguish Executable / Verifiable / Cryptographically Attested.
        A run is only 'attested' when verdict is VERIFIED, execution mode is live/hybrid,
        signatures are cryptographically verified, and evidence is complete.
        """
        if self.verdict != Verdict.VERIFIED:
            return "not_applicable"
        if not self.signature_verified or not self.evidence_complete:
            return "verifiable" if self.execution_mode in ("live", "hybrid") else "simulated"
        return "attested" if self.execution_mode in ("live", "hybrid") else "verifiable"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["assertions"] = [
            a.to_dict() if isinstance(a, AssertionResult) else a for a in self.assertions
        ]
        data["transitions"] = [
            t.to_dict() if isinstance(t, TransitionEvidence) else t for t in self.transitions
        ]
        data["attestation_grade"] = self.attestation_grade
        data["contracts_version"] = CONTRACTS_VERSION
        return data

    @classmethod
    def from_session_decision(
        cls, decision: dict[str, Any], *, execution_mode: str = "simulated"
    ) -> VerificationResult:
        """
        Adapts the SessionManager._build_verification_decision payload into the
        canonical contract so kernel and API share one source of truth.
        """
        identity = decision.get("identity", {})
        mapping = {
            "PASS": Verdict.VERIFIED,
            "FAIL": Verdict.NOT_VERIFIED,
            "EVALUATION_INVALID": Verdict.EVALUATION_INVALID,
        }
        assertions = [
            a
            if isinstance(a, AssertionResult)
            else AssertionResult(
                assertion_id=str(a.get("metric") or a.get("assertion") or "unnamed"),
                kind=str(a.get("source", "metric")),
                node_id=a.get("node"),
                passed=bool(a.get("passed")),
                severity=a.get("severity", "required"),
                expected=a.get("expected"),
                actual=a.get("actual_after", a.get("actual")),
                actual_before=a.get("actual_before"),
                mode=a.get("mode"),
                reason=a.get("reason"),
                invalid=bool(a.get("invalid")),
            )
            for a in decision.get("assertions", [])
        ]
        transitions = [
            t
            if isinstance(t, TransitionEvidence)
            else TransitionEvidence(
                from_node=t.get("from_node", ""),
                to_node=t.get("to_node", ""),
                selected_edge_id=t.get("selected_edge_id", ""),
                edge_type=t.get("edge_type", ""),
                transition_reason=t.get("transition_reason", ""),
                evaluated_predicate=t.get("evaluated_predicate"),
                observed_value=t.get("observed_value"),
                source_execution_id=t.get("source_execution_id"),
                target_execution_id=t.get("target_execution_id"),
            )
            for t in decision.get("expected_transitions", [])
        ]
        sig_verified = False
        if "signature_verified" in decision:
            sig_verified = bool(decision["signature_verified"])
        elif "signature_verified" in identity:
            sig_verified = bool(identity["signature_verified"])
        elif decision.get("signatures") and not decision.get("signature_error"):
            sig_verified = True

        evidence_complete = False
        if "evidence_complete" in decision:
            evidence_complete = bool(
                decision["evidence_complete"] and not decision.get("evidence_missing", False)
            )
        elif "evidence_complete" in identity:
            evidence_complete = bool(identity["evidence_complete"])

        return cls(
            evaluation_run_id=identity.get("evaluation_run_id", ""),
            scenario_version_id=identity.get("scenario_version_id", ""),
            case_id=identity.get("case_id", ""),
            attempt_id=identity.get("attempt_id", ""),
            attempt_number=int(identity.get("attempt_number", 1)),
            execution_mode=identity.get("execution_mode", execution_mode),
            verdict=mapping.get(decision.get("decision"), Verdict.INCONCLUSIVE),
            because=list(decision.get("because", [])),
            assertions=assertions,
            transitions=transitions,
            observed_execution=list(decision.get("observed_execution", [])),
            policy_checks=list(decision.get("policy_checks", [])),
            evidence_refs=list(decision.get("evidence_refs", [])),
            signature_verified=sig_verified,
            evidence_complete=evidence_complete,
            signer_identity=decision.get("signer_identity") or identity.get("signer_identity"),
            manifest_digest=decision.get("manifest_digest") or identity.get("manifest_digest"),
            workflow_status=decision.get("workflow_status", ""),
            ir_version=decision.get("ir_version", ""),
        )


@dataclass(frozen=True)
class RCAResult:
    """
    Root-cause analysis result with mandatory confidence labeling.
    'root cause' and 'first correlated failure' must never be conflated.
    """

    confidence: str  # confirmed | suspected | detected
    failure_class: str
    node_id: str | None = None
    event_ref: str | None = None
    evidence_chain: list[dict[str, Any]] = field(default_factory=list)
    violated_assertion: AssertionResult | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if isinstance(self.violated_assertion, AssertionResult):
            data["violated_assertion"] = self.violated_assertion.to_dict()
        return data


@dataclass(frozen=True)
class EvidenceArtifact:
    """One immutable artifact in the Run -> ... -> Bundle chain."""

    artifact_id: str
    run_id: str
    name: str
    uri: str
    content_hash: str  # sha3_256:<hex>
    artifact_type: str  # trace_events | manifest | certificate | scenario | bundle
    certified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "AssertionResult",
    "CONTRACTS_VERSION",
    "EvidenceArtifact",
    "ExecutionMode",
    "RCAResult",
    "ReadinessTier",
    "RuntimeHealth",
    "TransitionEvidence",
    "Verdict",
    "VerificationResult",
]
