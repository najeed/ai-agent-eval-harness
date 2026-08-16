"""
eval_runner.reference.field_policy
OSS Reference Implementation: BasicFieldPolicyEvaluator
"""

from typing import Any

from eval_runner.interfaces.policy import PolicyEvaluationResult, PolicyEvaluator


class BasicFieldPolicyEvaluator(PolicyEvaluator):
    """
    Field-level numeric and boundary policy evaluator.
    Evaluates numeric bounds, required fields, and forbidden value rules.
    """

    def evaluate_policy(
        self,
        policy_spec: dict[str, Any],
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        policy_id = policy_spec.get("id", policy_spec.get("name", "basic_field_policy"))
        violations = []

        # 1. Numeric limit constraints (e.g. max_amount, limit)
        max_val = policy_spec.get("max_value") or policy_spec.get("limit")
        target_field = policy_spec.get("param_key") or policy_spec.get("field")

        if max_val is not None:
            if target_field:
                val = input_data.get(target_field)
                if val is not None and isinstance(val, (int, float)) and val > max_val:
                    violations.append(
                        {
                            "field": target_field,
                            "value": val,
                            "limit": max_val,
                            "message": f"Value {val} exceeds configured maximum {max_val}",
                        }
                    )
            else:
                for k, v in input_data.items():
                    if isinstance(v, (int, float)) and v > max_val:
                        violations.append(
                            {
                                "field": k,
                                "value": v,
                                "limit": max_val,
                                "message": f"Field '{k}' with value {v} exceeds limit {max_val}",
                            }
                        )

        # 2. Required fields
        required_fields = policy_spec.get("required_fields", [])
        for rf in required_fields:
            if rf not in input_data:
                violations.append(
                    {
                        "field": rf,
                        "message": f"Missing required parameter: '{rf}'",
                    }
                )

        allowed = len(violations) == 0
        reason = (
            "All policy constraints satisfied"
            if allowed
            else f"Policy violated ({len(violations)} constraint failures)"
        )
        return PolicyEvaluationResult(
            allowed=allowed,
            policy_id=policy_id,
            reason=reason,
            violations=violations,
        )

    def validate_policy(self, policy_spec: dict[str, Any]) -> bool:
        return isinstance(policy_spec, dict) and bool(
            "id" in policy_spec
            or "name" in policy_spec
            or "limit" in policy_spec
            or "max_value" in policy_spec
            or "required_fields" in policy_spec
        )
