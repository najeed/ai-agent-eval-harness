"""Observe injected rollback failures at the scheduler's compensation dispatch boundary."""

from types import SimpleNamespace

from eval_runner.mutations.mutation_registry import selected_faults
from eval_runner.mutations.runtime_faults import FaultDeliveryController


def intercept_compensation(run_id, bus, plugins, scenario, node, execution_id, parent_id):
    if "rollback_failure" not in selected_faults(
        node, scenario, scenario.get("metadata"), scenario.get("failure_policy")
    ):
        return None
    owner = SimpleNamespace(scenario=scenario, current_execution_instance_id=execution_id)
    plugins.trigger_interceptor("on_step_start", owner, node["id"], node)
    try:
        decision = plugins.trigger_interceptor(
            "on_rollback", owner, {"node_id": node["id"], "parent_execution_id": parent_id}
        )
    finally:
        plugins.trigger_interceptor("on_step_end", owner, node["id"])
    if (
        not isinstance(decision, dict)
        or decision.get("runtime_fault", {}).get("fault") != "rollback_failure"
    ):
        raise RuntimeError("Selected rollback fault did not reach its mandatory interceptor")
    controller = FaultDeliveryController(run_id, bus)
    identity = controller._identity("rollback_failure", node["id"], execution_id)
    scheduled = controller._observe(
        "compensation_scheduled",
        identity,
        {
            "parent_execution_id": parent_id,
            "compensating": True,
        },
    )
    observed = {
        "parent_execution_id": parent_id,
        "compensating": True,
        "handler_dispatched": False,
        "blocked_by_fault": True,
    }
    blocked = controller._observe("compensation_dispatch_blocked", identity, observed)
    controller._receipt(identity, [scheduled, blocked], observed)
    return {
        "task_id": node["id"],
        "status": "failure",
        "triage_tag": "MUTATION_OBSERVED",
        "message": "Rollback handler dispatch blocked by the injected fault",
        "mutation_fault": "rollback_failure",
        "turns_taken": 0,
        "used_tools": [],
        "conversation_history": [],
    }
