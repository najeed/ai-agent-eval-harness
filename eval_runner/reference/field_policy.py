"""
eval_runner.reference.field_policy
OSS Reference Implementation: BasicFieldPolicyEvaluator & RegulatoryPolicyEvaluator (P0-07).
Evaluates numeric bounds, required fields, and statutory regulatory mandates
via a pure declarative AST condition-constraint engine.
"""

from typing import Any

from eval_runner.interfaces.policy import PolicyEvaluationResult, PolicyEvaluator

# Canonical Pre-Compiled Declarative Rules for Reference Standards
STANDARD_DECLARATIVE_RULES: dict[str, list[dict[str, Any]]] = {
    "WA_ESSB_5395": [
        {
            "rule_id": "wa_essb_5395_clinical_context",
            "when": {
                "field": ["decision", "status", "action", "outcome"],
                "operator": "in",
                "values": [
                    "DENY",
                    "DENIED",
                    "DOWNGRADE",
                    "DOWNGRADED",
                    "DELAY",
                    "DELAYED",
                    "MODIFIED",
                    "REJECT",
                    "REJECTED",
                    "PARTIAL_APPROVAL",
                ],
            },
            "require_any": [
                "clinical_context",
                "clinical_records",
                "patient_notes",
                "chart_history",
                "medical_records",
                "clinical_documentation",
                "evidence",
            ],
            "statutory_code": "WA_ESSB_5395_MISSING_CLINICAL_EVALUATION",
            "citation": "WA ESSB 5395 § 2(1)",
            "message": (
                "Statutory violation under WA ESSB 5395: Adverse determination "
                "issued without patient clinical documentation evaluation."
            ),
        },
        {
            "rule_id": "wa_essb_5395_clinical_rationale",
            "when": {
                "field": ["decision", "status", "action", "outcome"],
                "operator": "in",
                "values": [
                    "DENY",
                    "DENIED",
                    "DOWNGRADE",
                    "DOWNGRADED",
                    "DELAY",
                    "DELAYED",
                    "MODIFIED",
                    "REJECT",
                    "REJECTED",
                    "PARTIAL_APPROVAL",
                ],
            },
            "require_any": [
                "clinical_rationale",
                "medical_necessity_rationale",
                "clinical_citations",
                "rationale",
                "denial_reason_clinical",
            ],
            "statutory_code": "WA_ESSB_5395_MISSING_CLINICAL_RATIONALE",
            "citation": "WA ESSB 5395 § 2(2)",
            "message": (
                "Statutory violation under WA ESSB 5395: Adverse determination "
                "cannot rely solely on automated decision systems without clinical rationale."
            ),
        },
    ],
    "IA_HF_2635": [
        {
            "rule_id": "ia_hf_2635_licensed_physician_review",
            "when": {
                "field": ["decision", "status", "action", "outcome"],
                "operator": "in",
                "values": [
                    "DENY",
                    "DENIED",
                    "DOWNGRADE",
                    "DOWNGRADED",
                    "DELAY",
                    "DELAYED",
                    "MODIFIED",
                    "REJECT",
                    "REJECTED",
                    "PARTIAL_APPROVAL",
                ],
            },
            "require_any": [
                "licensed_physician_review",
                "human_reviewer_id",
                "physician_license",
                "reviewer_credential",
                "human_review_artifact",
                "licensed_reviewer",
            ],
            "valid_status_field": "review_status",
            "valid_statuses": [
                "COMPLETED",
                "APPROVED_BY_PHYSICIAN",
                "REVIEWED",
                "LICENSED_REVIEW_COMPLETE",
            ],
            "bypass_flag": "human_in_the_loop",
            "statutory_code": "IA_HF_2635_UNLICENSED_ADVERSE_DECISION",
            "citation": "IA HF 2635 § 1",
            "message": (
                "Statutory violation under IA HF 2635: Adverse utilization review "
                "determination must be reviewed by a licensed physician or clinical professional."
            ),
        }
    ],
}


def match_condition(condition: dict[str, Any] | None, input_data: dict[str, Any]) -> bool:
    """
    Evaluates whether input_data matches the given AST condition.
    Supports single or multi-field lookup, operators:
    in, eq, ne, contains, gte, lte, exists, not_exists.
    """
    if not condition:
        return True

    field_spec = condition.get("field")
    if not field_spec:
        return True

    field_candidates = [field_spec] if isinstance(field_spec, str) else list(field_spec)
    val = None
    field_found = False
    for f in field_candidates:
        if f in input_data:
            val = input_data[f]
            field_found = True
            break

    op = str(condition.get("operator", "in" if "values" in condition else "eq")).lower()
    values = condition.get("values", condition.get("value"))

    if op == "exists":
        return field_found and bool(val)
    if op == "not_exists":
        return not field_found or not bool(val)

    if not field_found or val is None:
        return False

    str_val = str(val).upper().strip()

    if op == "in":
        if isinstance(values, (list, tuple, set)):
            target_set = {str(v).upper().strip() for v in values}
            return any(t in str_val or str_val == t for t in target_set)
        return str(values).upper().strip() in str_val

    if op == "eq":
        return str_val == str(values).upper().strip()

    if op == "ne":
        return str_val != str(values).upper().strip()

    if op == "contains":
        return str(values).upper().strip() in str_val

    if op in ("gte", "lte", "gt", "lt"):
        if isinstance(val, (int, float)) and isinstance(values, (int, float)):
            if op == "gte":
                return val >= values
            if op == "lte":
                return val <= values
            if op == "gt":
                return val > values
            if op == "lt":
                return val < values
        return False

    return True


def evaluate_declarative_rule(
    rule: dict[str, Any],
    input_data: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Evaluates a single declarative condition-constraint rule against input_data.
    Supports:
      - when: AST trigger conditions
      - require_any: At least one field must be present and truthy
      - require_all: All listed fields must be present and truthy
      - forbidden: None of the listed fields may be present and truthy
      - min_length: String length validation
      - bounds: Numeric min/max limits
      - mode: "deterministic" (default), "semantic", or "hybrid" (short-circuiting)
      - Multi-reason failure aggregation with exact statutory pinpointing.
    """
    when_cond = rule.get("when")
    if when_cond and not match_condition(when_cond, input_data):
        return None

    # Check rule bypass flags (e.g. human_in_the_loop == True)
    bypass_flag = rule.get("bypass_flag")
    if bypass_flag and input_data.get(bypass_flag) is True:
        return None

    # Check valid status bypass (e.g. review_status == "COMPLETED")
    status_field = rule.get("valid_status_field")
    valid_statuses = rule.get("valid_statuses", [])
    if status_field and valid_statuses:
        current_status = str(input_data.get(status_field, "")).upper().strip()
        if current_status in {str(s).upper().strip() for s in valid_statuses}:
            return None

    sub_violations: list[dict[str, Any]] = []

    # 1. require_any constraint
    require_any = rule.get("require_any")
    if require_any:
        keys = [require_any] if isinstance(require_any, str) else require_any
        has_any = any(k in input_data and bool(input_data[k]) for k in keys)
        if not has_any:
            sub_violations.append(
                {
                    "field": keys[0],
                    "expected_one_of": keys,
                    "reason": f"Missing required parameter (expected one of: {keys})",
                }
            )

    # 2. require_all constraint
    require_all = rule.get("require_all")
    if require_all:
        keys = [require_all] if isinstance(require_all, str) else require_all
        for k in keys:
            if k not in input_data or not bool(input_data[k]):
                sub_violations.append(
                    {
                        "field": k,
                        "reason": f"Missing mandatory parameter: '{k}'",
                    }
                )

    # 3. forbidden constraint
    forbidden = rule.get("forbidden")
    if forbidden:
        keys = [forbidden] if isinstance(forbidden, str) else forbidden
        for k in keys:
            if k in input_data and bool(input_data[k]):
                sub_violations.append(
                    {
                        "field": k,
                        "reason": f"Forbidden parameter '{k}' is present in payload",
                    }
                )

    # 4. min_length constraint
    min_length_spec = rule.get("min_length")
    if isinstance(min_length_spec, dict):
        for f, m_len in min_length_spec.items():
            val = input_data.get(f)
            if val is not None and len(str(val)) < m_len:
                sub_violations.append(
                    {
                        "field": f,
                        "reason": (
                            f"Parameter '{f}' length ({len(str(val))}) "
                            f"below required minimum of {m_len}"
                        ),
                    }
                )

    # 5. bounds constraint
    bounds_spec = rule.get("bounds")
    if isinstance(bounds_spec, dict):
        for f, b_info in bounds_spec.items():
            val = input_data.get(f)
            if isinstance(val, (int, float)) and isinstance(b_info, dict):
                max_b = b_info.get("max")
                min_b = b_info.get("min")
                if max_b is not None and val > max_b:
                    sub_violations.append(
                        {
                            "field": f,
                            "reason": (
                                f"Parameter '{f}' with value {val} exceeds maximum bound of {max_b}"
                            ),
                        }
                    )
                if min_b is not None and val < min_b:
                    sub_violations.append(
                        {
                            "field": f,
                            "reason": (
                                f"Parameter '{f}' with value {val} "
                                f"falls below minimum bound of {min_b}"
                            ),
                        }
                    )

    # Hybrid mode handling: if deterministic checks fail, short-circuit immediately!
    mode = str(rule.get("mode", "deterministic")).lower()
    if sub_violations:
        # Short-circuit on deterministic failure
        statutory_code = rule.get("statutory_code") or rule.get("code", "POLICY_VIOLATION")
        citation = rule.get("citation")
        base_message = rule.get("message")
        primary_field = sub_violations[0]["field"]

        reasons = [sv["reason"] for sv in sub_violations]
        if len(sub_violations) > 1:
            details = "\n".join(f" - [{statutory_code}] {r}" for r in reasons)
            rule_label = rule.get("rule_id", "unnamed")
            if base_message:
                composite_msg = (
                    f"{base_message} ({len(sub_violations)} constraint failures):\n{details}"
                )
            else:
                composite_msg = (
                    f"Rule '{rule_label}' failed "
                    f"({len(sub_violations)} constraint failures):\n{details}"
                )
        else:
            rule_label = rule.get("rule_id", "unnamed")
            composite_msg = base_message or f"Rule '{rule_label}' violation: {reasons[0]}"

        violation_entry = {
            "field": primary_field,
            "code": statutory_code,
            "message": composite_msg,
            "reasons": reasons,
            "sub_violations": sub_violations,
        }
        if citation:
            violation_entry["citation"] = citation
        return violation_entry

    # If deterministic passed, check if semantic/judge check is required
    if mode in ("semantic", "hybrid") and "semantic" in rule:
        semantic_spec = rule["semantic"]
        # If semantic evaluation flag or context indicates LLM judge is active
        judge_fn = (context or {}).get("llm_judge")
        if callable(judge_fn):
            rubric = semantic_spec.get("rubric", "general_compliance")
            min_score = semantic_spec.get("min_score", 0.8)
            score, feedback = judge_fn(rubric=rubric, input_data=input_data)
            if score < min_score:
                statutory_code = rule.get("statutory_code") or rule.get(
                    "code", "SEMANTIC_RUBRIC_FAILURE"
                )
                return {
                    "field": rule.get("field", "payload"),
                    "code": statutory_code,
                    "message": (
                        f"Semantic judge rubric '{rubric}' failed "
                        f"({score} < {min_score}): {feedback}"
                    ),
                    "score": score,
                    "rubric": rubric,
                }

    return None


def evaluate_regulatory_policy(
    policy_spec: dict[str, Any],
    input_data: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Evaluates regulatory policies using the pure declarative engine.
    Supports custom declarative rules supplied in policy_spec['rules'],
    or canonical pre-compiled rules for WA ESSB 5395 and IA HF 2635.
    """
    violations: list[dict[str, Any]] = []

    # 1. Custom declarative rules (Supplied Fuel from Control Plane)
    custom_rules = policy_spec.get("rules")
    if isinstance(custom_rules, list):
        for r in custom_rules:
            if isinstance(r, dict):
                v = evaluate_declarative_rule(r, input_data, context=context)
                if v:
                    violations.append(v)
        return violations

    # 2. Standard resolution (WA ESSB 5395, IA HF 2635)
    standard = (
        policy_spec.get("standard")
        or policy_spec.get("regulatory_standard")
        or policy_spec.get("id")
        or ""
    ).upper()

    active_rules: list[dict[str, Any]] = []
    if "WA_ESSB_5395" in standard or "5395" in standard or policy_spec.get("enforce_wa_essb_5395"):
        active_rules.extend(STANDARD_DECLARATIVE_RULES["WA_ESSB_5395"])

    if "IA_HF_2635" in standard or "2635" in standard or policy_spec.get("enforce_ia_hf_2635"):
        active_rules.extend(STANDARD_DECLARATIVE_RULES["IA_HF_2635"])

    for r in active_rules:
        v = evaluate_declarative_rule(r, input_data, context=context)
        if v:
            violations.append(v)

    return violations


class BasicFieldPolicyEvaluator(PolicyEvaluator):
    """
    Field-level numeric, boundary, and regulatory policy evaluator.
    Evaluates numeric bounds, constrained parameters, required fields,
    forbidden value rules, and declarative regulatory policies.
    """

    def evaluate_policy(
        self,
        policy_spec: dict[str, Any],
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        policy_id = policy_spec.get("id", policy_spec.get("name", "basic_field_policy"))
        violations: list[dict[str, Any]] = []

        # 0. Declarative Regulatory Policy checks (P0-07)
        regulatory_violations = evaluate_regulatory_policy(policy_spec, input_data, context=context)
        violations.extend(regulatory_violations)

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

        # Declarative rules array
        if "rules" in policy_spec and isinstance(policy_spec["rules"], (list, tuple)):
            return True

        # Standard resolution specs are valid
        standard = str(
            policy_spec.get("standard")
            or policy_spec.get("regulatory_standard")
            or policy_spec.get("id")
            or ""
        ).upper()
        if any(reg in standard for reg in ["WA_ESSB_5395", "5395", "IA_HF_2635", "2635"]):
            return True

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


class RegulatoryPolicyEvaluator(BasicFieldPolicyEvaluator):
    """Dedicated evaluator for statutory regulatory policies."""
