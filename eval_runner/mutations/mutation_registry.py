"""Canonical mutation capabilities and declaration compilation for runtime and verification."""

from collections.abc import Mapping

FAULT_FLAGS = {
    "cancel_race": "cancel_at_boundary",
    "commit_after_cancel": "commit_after_cancel",
    "partial_commit": "partial_commit_simulated",
    "stale_commit": "stale_commit",
    "approval_stale": "approval_stale",
    "approval_mismatch": "approval_mismatch",
    "approval_replay": "approval_replay",
    "approval_race": "approval_race",
    "approval_revocation": "approval_revocation",
    "timeout_boundary": "timeout_boundary_ms",
    "malformed_payload": "raw_payload_corrupted",
    "tool_duplicate": "duplicate_execution",
    "tool_replay": "replay_previous_event",
    "latency_jitter": "injected_latency_ms",
    "tool_response_corruption": "tool_response_corrupted",
    "tool_contract": "tool_contract_violation",
    "rollback_failure": "rollback_handler_corrupted",
}
ALIASES = {
    "duplicate": "tool_duplicate",
    "duplicate_action": "tool_duplicate",
    "replay": "tool_replay",
    "cancel": "cancel_race",
    "cancellation_race": "cancel_race",
    "cancellation race": "cancel_race",
    "auth_stale": "approval_stale",
    "stale_approval": "approval_stale",
    "auth_mismatch": "approval_mismatch",
    "mismatch": "approval_mismatch",
    "auth_replay": "approval_replay",
    "auth_race": "approval_race",
    "race": "approval_race",
    "auth_revocation": "approval_revocation",
    "revocation": "approval_revocation",
    "partial commit": "partial_commit",
    "partial": "partial_commit",
    "stale commit": "stale_commit",
    "after-cancel commit": "commit_after_cancel",
    "after_cancel_commit": "commit_after_cancel",
    "after-cancel": "commit_after_cancel",
    "timeout": "timeout_boundary",
    "malformed payload": "malformed_payload",
    "malformed": "malformed_payload",
    "latency jitter": "latency_jitter",
    "latency": "latency_jitter",
    "jitter": "latency_jitter",
    "rollback failure": "rollback_failure",
    "rollback": "rollback_failure",
    "contract violation": "tool_contract",
    "contract_violation": "tool_contract",
}
SCENARIO_EDITS = frozenset(
    {
        "typo",
        "ambiguity",
        "injection",
        "goal_drift",
        "constraint_drop",
        "memory_drift",
        "retrieval_stale",
        "retrieval_irrelevant",
        "retrieval_conflict",
        "retrieval_chunk",
        "retrieval_source_swap",
        "schema_type",
        "missing_field",
        "enum_drift",
        "stale_state",
        "metric_gaming",
        "proxy_goal",
        "constraint_tradeoff",
        "subgoal_cannibalization",
        "reward_hacking",
    }
)
EDIT_ALIASES = {
    "typos": "typo",
    "stale": "retrieval_stale",
    "irrelevant": "retrieval_irrelevant",
    "conflict": "retrieval_conflict",
    "conflicting": "retrieval_conflict",
    "chunk": "retrieval_chunk",
    "source_swap": "retrieval_source_swap",
    "source-swap": "retrieval_source_swap",
    "type_mutation": "schema_type",
    "schema/type": "schema_type",
    "schema": "schema_type",
    "type": "schema_type",
    "missing-field": "missing_field",
    "enum_shift": "enum_drift",
    "enum": "enum_drift",
    "stale state": "stale_state",
    "metric gaming": "metric_gaming",
    "gaming": "metric_gaming",
    "proxy goal": "proxy_goal",
    "proxy": "proxy_goal",
    "constraint tradeoff": "constraint_tradeoff",
    "tradeoff": "constraint_tradeoff",
    "subgoal cannibalization": "subgoal_cannibalization",
    "cannibalization": "subgoal_cannibalization",
    "reward hacking": "reward_hacking",
    "reward": "reward_hacking",
}


def canonical_edit(name):
    if not isinstance(name, str):
        return None
    return name if name in SCENARIO_EDITS else EDIT_ALIASES.get(name)


def canonical_fault(name):
    if not isinstance(name, str):
        return None
    return name if name in FAULT_FLAGS else ALIASES.get(name)


def declaration_layers(source):
    if not isinstance(source, Mapping):
        return
    yield source
    for key in ("mutations", "adversarial_mutation"):
        nested = source.get(key)
        if isinstance(nested, Mapping):
            yield nested


def selected_faults(*sources):
    selected = set()
    for source in sources:
        for layer in declaration_layers(source):
            for fault, flag in FAULT_FLAGS.items():
                if (
                    (fault == "malformed_payload" and flag in layer)
                    or layer.get(flag)
                    or layer.get(fault) is True
                ):
                    selected.add(fault)
            for key in ("mutation_fault", "approval_fault", "fault", "type"):
                fault = canonical_fault(layer.get(key))
                if fault:
                    selected.add(fault)
                elif (
                    key != "type"
                    and isinstance(layer.get(key), str)
                    and layer[key]
                    and canonical_edit(layer[key]) is None
                ):
                    selected.add(layer[key])
    return selected


def runtime_plan(*sources):
    plan = {}
    for source in reversed(sources):
        for layer in declaration_layers(source):
            plan.update(layer)
    for fault in selected_faults(*sources):
        if fault not in FAULT_FLAGS:
            raise ValueError(f"Unregistered runtime mutation: {fault}")
        flag = FAULT_FLAGS[fault]
        if flag not in plan:
            plan[flag] = {
                "timeout_boundary": 50,
                "latency_jitter": 500,
                "malformed_payload": '{"unclosed',
            }.get(fault, True)
    return plan


def required_deliveries(scenario):
    workflow = scenario.get("workflow") or []
    nodes = workflow.get("nodes", []) if isinstance(workflow, Mapping) else workflow
    inherited = selected_faults(scenario, scenario.get("metadata"), scenario.get("failure_policy"))
    required = set()
    for node in nodes:
        faults = selected_faults(node) | inherited
        for fault in faults:
            # The latency attached to a deadline is the deadline stimulus;
            # independent latency jitter is a separate requested fault.
            if fault == "latency_jitter" and "timeout_boundary" in faults:
                continue
            required.add(
                (
                    fault,
                    None
                    if fault == "rollback_failure" and fault in inherited
                    else node.get("id") or node.get("node_id"),
                )
            )
    for row in (scenario.get("metadata") or {}).get("applied_mutations", []):
        name = row.get("type") if isinstance(row, Mapping) else None
        fault = canonical_fault(name)
        if fault is None and isinstance(name, str) and name and canonical_edit(name) is None:
            fault = name
        if fault:
            target = row.get("node_id") or row.get("target_node")
            if target is not None or not any(existing == fault for existing, _ in required):
                required.add((fault, target))
    return required


def capability(name):
    if canonical_fault(name):
        return {"kind": "runtime_fault", "delivery_evidence_required": True}
    if canonical_edit(name):
        return {
            "kind": "scenario_edit",
            "delivery_evidence_required": False,
            "execution_delivery_claim": False,
        }
    return {"kind": "extension", "delivery_evidence_required": True}
