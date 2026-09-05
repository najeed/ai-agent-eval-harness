"""
tests.acceptance.result
Authoritative Acceptance Certification Result Contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AcceptanceResult:
    """
    Contract representing the acceptance evaluation of an AgentV test case.
    Separated strictly from internal execution/evaluation runtime contracts.
    """

    case_id: str
    accepted: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    failures: tuple[str, ...]
    run_id: str
    agentv_version: str
    git_commit: str
    evidence_verified: bool
    certificate_verified: bool
    ledger_verified: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize AcceptanceResult to JSON-compatible dictionary."""
        data = asdict(self)
        data["failures"] = list(self.failures)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcceptanceResult:
        """Construct AcceptanceResult from dictionary representation."""
        return cls(
            case_id=str(data["case_id"]),
            accepted=bool(data["accepted"]),
            expected=dict(data.get("expected", {})),
            actual=dict(data.get("actual", {})),
            failures=tuple(data.get("failures", ())),
            run_id=str(data.get("run_id", "")),
            agentv_version=str(data.get("agentv_version", "unknown")),
            git_commit=str(data.get("git_commit", "unknown")),
            evidence_verified=bool(data.get("evidence_verified", False)),
            certificate_verified=bool(data.get("certificate_verified", False)),
            ledger_verified=bool(data.get("ledger_verified", False)),
        )


__all__ = ["AcceptanceResult"]
