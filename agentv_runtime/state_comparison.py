"""
agentv_runtime/state_comparison.py
Authoritative StateComparison evidence contract.
Carries structured diff and causality references for live debugger RCA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class StateComparison:
    """
    Authoritative state comparison payload emitted on parity or assertion failure.
    Carries scenario_node_id, execution_instance_id, assertion_id, expected, actual,
    comparison_result, and causal evidence reference.
    """

    scenario_node_id: str
    execution_instance_id: str
    assertion_id: str
    expected: Any
    actual: Any
    comparison_result: str = "diverged"
    evidence_ref: str = "run.jsonl"
    comparison: dict[str, Any] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    source: str = "state_parity"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        comp = (
            dict(self.comparison)
            if self.comparison
            else {
                "kind": "state_comparison",
                "result": self.comparison_result,
                "failed_assertion": self.assertion_id,
            }
        )
        return {
            "scenario_node_id": self.scenario_node_id,
            "execution_instance_id": self.execution_instance_id,
            "assertion_id": self.assertion_id,
            "expected": self.expected,
            "actual": self.actual,
            "comparison_result": self.comparison_result,
            "evidence_ref": self.evidence_ref,
            "comparison": comp,
            "assertions": list(self.assertions) if self.assertions else [],
            "source": self.source,
            "timestamp": self.timestamp,
        }


__all__ = ["StateComparison"]
