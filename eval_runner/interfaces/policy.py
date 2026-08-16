"""
eval_runner.interfaces.policy
Public Extension Family: PolicyEvaluator Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class PolicyEvaluationResult:
    """Standard result structure for a policy evaluation decision."""

    def __init__(
        self,
        allowed: bool,
        policy_id: str,
        reason: str | None = None,
        violations: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.allowed = allowed
        self.policy_id = policy_id
        self.reason = reason or ("Policy passed" if allowed else "Policy violated")
        self.violations = violations or []
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "policy_id": self.policy_id,
            "reason": self.reason,
            "violations": self.violations,
            "metadata": self.metadata,
        }


class PolicyEvaluator(ABC):
    """
    Abstraction for policy rule evaluation and runtime sandbox constraint gating.
    OSS Reference: BasicFieldPolicyEvaluator
    Control Plane / Enterprise: OPAPolicyEvaluator / CedarPolicyEvaluator
    """

    @abstractmethod
    def evaluate_policy(
        self,
        policy_spec: dict[str, Any],
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        """Evaluates input data against a policy specification."""
        raise NotImplementedError

    @abstractmethod
    def validate_policy(self, policy_spec: dict[str, Any]) -> bool:
        """Validates that a policy specification schema is syntactically correct and supported."""
        raise NotImplementedError
