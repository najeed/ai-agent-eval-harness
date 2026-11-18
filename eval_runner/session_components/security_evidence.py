"""Compile typed denial results from the node's upfront oracle inventory."""

from eval_runner.events import CoreEvents


def record_security_rejection(
    bus, run_id, node_id, fault, error, resolver, evaluation_plan, span_context=None
):
    results = security_rejection_oracles(node_id, fault, error, resolver, evaluation_plan)
    for oracle in results:
        bus.emit(
            CoreEvents.ASSERTION_EVALUATED,
            {**oracle, "run_id": run_id, "node_id": node_id, "passed": False},
            span_context=span_context,
        )
    return results


def security_rejection_oracles(node_id, fault, error, resolver, evaluation_plan):
    primary_id = f"security:{fault}"
    results = [
        {
            "oracle_id": primary_id,
            "scenario_node_id": node_id,
            "resolver": resolver,
            "requiredness": "REQUIRED",
            "outcome": "FAIL",
            "error": error,
            "expected": "ALLOWED",
            "observed": "REJECTED",
        }
    ]
    if evaluation_plan is not None:
        for required in evaluation_plan.required_oracles_for_node(node_id):
            if required.oracle_id != primary_id:
                results.append(
                    {
                        **results[0],
                        "oracle_id": required.oracle_id,
                        "resolver": required.resolver or resolver,
                        "error": f"Security boundary prevented evaluation: {error}",
                    }
                )
    return results
