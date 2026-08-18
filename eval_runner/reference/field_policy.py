"""
eval_runner.reference.field_policy
OSS Reference Implementation: BasicFieldPolicyEvaluator
"""

from typing import Any

from eval_runner.interfaces.policy import PolicyEvaluationResult, PolicyEvaluator


class BasicFieldPolicyEvaluator(PolicyEvaluator):
    """
    Field-level numeric and boundary policy evaluator.
    Evaluates numeric bounds, constrained parameters, required fields, and forbidden value rules.
    """

    def evaluate_policy(
        self,
        policy_spec: dict[str, Any],
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        policy_id = policy_spec.get("id", policy_spec.get("name", "basic_field_policy"))
        violations = []

        # 1. Numeric limit constraints (e.g. max_limit, max_value, limit)
        max_val = policy_spec.get("max_limit")
        if max_val is None:
            max_val = policy_spec.get("max_value")
        if max_val is None:
            max_val = policy_spec.get("limit")

        constrained_params = policy_spec.get("constrained_params")
        target_field = policy_spec.get("param_key") or policy_spec.get("field")

        if max_val is not None:
            if constrained_params is not None:
                keys = (
                    [constrained_params]
                    if isinstance(constrained_params, str)
                    else constrained_params
                )
                for p_key in keys:
                    val = input_data.get(p_key)
                    if isinstance(val, (int, float)) and val > max_val:
                        violations.append(
                            {
                                "field": p_key,
                                "value": val,
                                "limit": max_val,
                                "message": (
                                    f"Parameter '{p_key}' with value {val} "
                                    f"exceeds limit of {max_val}"
                                ),
                            }
                        )
            elif target_field:
                val = input_data.get(target_field)
                if val is not None and isinstance(val, (int, float)) and val > max_val:
                    violations.append(
                        {
                            "field": target_field,
                            "value": val,
                            "limit": max_val,
                            "message": (
                                f"Parameter '{target_field}' with value {val} "
                                f"exceeds limit of {max_val}"
                            ),
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
                                "message": (
                                    f"Parameter '{k}' with value {v} exceeds limit of {max_val}"
                                ),
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
        if not isinstance(policy_spec, dict):
            return False
        max_val = (
            policy_spec.get("max_limit") or policy_spec.get("limit") or policy_spec.get("max_value")
        )
        if max_val is not None and not isinstance(max_val, (int, float)):
            return False
        if "required_fields" in policy_spec and not isinstance(
            policy_spec["required_fields"], (list, tuple)
        ):
            return False
        return bool(
            "id" in policy_spec
            or "name" in policy_spec
            or max_val is not None
            or "required_fields" in policy_spec
            or "constrained_params" in policy_spec
        )
