"""
A6: IR semantic validation contract tests.

  1. Default-edge uniqueness per source node
  2. Conditional edges require distinct priorities (deterministic selection)
  3. Explicit join cardinality <= incoming degree
  4. Compensation legality (no self-compensation, target must be reachable)
  5. Loop SCC nodes must declare explicit max_visitations budgets
"""

import pytest

from eval_runner.execution_ir import (
    PlanValidationError,
    compile_evaluation_plan,
    compile_workflow,
)


def _scenario(nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "aes_version": 1.4,
        "workflow": {"nodes": nodes, "edges": edges},
    }


def _oracle(nid: str) -> dict:
    return {
        "id": nid,
        "task_description": nid,
        "success_criteria": [{"metric": "task_completion", "threshold": 1.0}],
    }


def test_default_uniqueness_violation_rejected():
    scenario = _scenario(
        [_oracle("a"), _oracle("b"), _oracle("c")],
        [
            {"from": "a", "to": "b", "type": "default"},
            {"from": "a", "to": "c", "type": "default"},
        ],
    )
    with pytest.raises(PlanValidationError, match="Ambiguous fallback"):
        compile_workflow(scenario)


def test_single_default_edge_accepted():
    scenario = _scenario(
        [_oracle("a"), _oracle("b"), _oracle("c")],
        [
            {"from": "a", "to": "b", "type": "condition", "predicate": {"op": "truthy"}},
            {"from": "a", "to": "c", "type": "default"},
        ],
    )
    plan = compile_workflow(scenario)
    assert plan.nodes["a"].definition["id"] == "a"


def test_duplicate_condition_priorities_rejected():
    scenario = _scenario(
        [_oracle("a"), _oracle("b"), _oracle("c")],
        [
            {"from": "a", "to": "b", "type": "condition", "predicate": True},
            {
                "from": "a",
                "to": "c",
                "type": "condition",
                "predicate": False,
                "priority": 100,
            },
        ],
    )
    # Both condition edges default to priority=100 -> ambiguous exclusivity.
    with pytest.raises(PlanValidationError, match="duplicate priorities"):
        compile_workflow(scenario)


def test_distinct_condition_priorities_accepted():
    scenario = _scenario(
        [_oracle("a"), _oracle("b"), _oracle("c")],
        [
            {"from": "a", "to": "b", "type": "condition", "predicate": True, "priority": 10},
            {"from": "a", "to": "c", "type": "condition", "predicate": True, "priority": 20},
            {"from": "b", "to": "c", "type": "default"},
        ],
    )
    compile_workflow(scenario)


def test_join_cardinality_exceeding_degree_rejected():
    scenario = _scenario(
        [
            _oracle("a"),
            {**_oracle("j"), "join_threshold": 3},
        ],
        [
            {"from": "a", "to": "j"},
        ],
    )
    with pytest.raises(PlanValidationError, match="Join cardinality"):
        compile_workflow(scenario)


def test_join_cardinality_within_degree_accepted():
    scenario = _scenario(
        [
            _oracle("a"),
            _oracle("b"),
            {**_oracle("j"), "join_threshold": 2},
        ],
        [
            {"from": "a", "to": "b"},
            {"from": "a", "to": "j"},
            {"from": "b", "to": "j"},
        ],
    )
    compile_workflow(scenario)


def test_self_compensation_rejected():
    scenario = _scenario(
        [_oracle("a")],
        [{"from": "a", "to": "a", "type": "compensation"}],
    )
    with pytest.raises(PlanValidationError, match="self-compensation"):
        compile_workflow(scenario)


def test_compensation_from_unreachable_source_rejected():
    # 'ghost' can never execute (no forward path from entry), so a failure
    # route originating from it is dead code and rejected.
    scenario = _scenario(
        [_oracle("entry"), _oracle("worker"), _oracle("ghost")],
        [
            {"from": "entry", "to": "worker"},
            {"from": "ghost", "to": "worker", "type": "compensation"},
        ],
    )
    scenario["workflow"]["entry_nodes"] = ["entry"]
    with pytest.raises(PlanValidationError, match="compensation originates from unreachable"):
        compile_workflow(scenario)


def test_compensate_then_fail_target_may_be_unexecuted():
    # compensate_then_fail semantics: the compensation target has NOT run
    # before — that is legal; it is executed as failure routing.
    scenario = _scenario(
        [_oracle("charge"), _oracle("refund")],
        [{"id": "e_comp", "from": "charge", "to": "refund", "type": "compensation"}],
    )
    compile_workflow(scenario)


def test_legal_backward_compensation_accepted():
    scenario = _scenario(
        [_oracle("entry"), _oracle("worker"), _oracle("cleanup")],
        [
            {"from": "entry", "to": "worker"},
            {"from": "worker", "to": "entry", "type": "compensation"},
            {"from": "worker", "to": "cleanup"},
        ],
    )
    compile_workflow(scenario)


def test_loop_scc_requires_explicit_visitation_budget():
    # entry -> loop_a -> loop_b -> loop_a (cycle), loop_b -> exit.
    nodes = [_oracle("entry"), _oracle("loop_a"), _oracle("loop_b"), _oracle("exit")]
    edges = [
        {"from": "entry", "to": "loop_a"},
        {"from": "loop_a", "to": "loop_b", "type": "retry"},
        {"from": "loop_b", "to": "loop_a", "type": "retry"},
        {"from": "loop_b", "to": "exit"},
    ]
    with pytest.raises(PlanValidationError, match="visitation budget"):
        compile_workflow(_scenario(nodes, edges))


def test_loop_scc_with_budgets_accepted():
    nodes = [
        _oracle("entry"),
        {**_oracle("loop_a"), "max_visitations": 5},
        {**_oracle("loop_b"), "max_visitations": 5},
        _oracle("exit"),
    ]
    edges = [
        {"from": "entry", "to": "loop_a"},
        {"from": "loop_a", "to": "loop_b", "type": "retry"},
        {"from": "loop_b", "to": "loop_a", "type": "retry"},
        {"from": "loop_b", "to": "exit"},
    ]
    plan = compile_workflow(_scenario(nodes, edges))
    assert plan.nodes["loop_a"].max_visitations == 5


def test_duplicate_oracle_id_rejected_at_compile_time():
    """[P0-Oracle] Compiler fails immediately on duplicate oracle IDs."""
    scenario = {
        "workflow": {
            "nodes": [
                {
                    "id": "node1",
                    "success_criteria": [
                        {"id": "duplicate_id", "metric": "accuracy"},
                        {"id": "duplicate_id", "metric": "exact_match"},
                    ],
                }
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Duplicate oracle_id 'duplicate_id'"):
        compile_evaluation_plan(scenario)


def test_malformed_assertion_rejected_at_compile_time():
    """[P0-Oracle] Compiler rejects non-dict assertion items rather than skipping."""
    scenario = {
        "workflow": {
            "nodes": [
                {
                    "id": "node1",
                    "success_criteria": ["invalid_string_assertion"],
                }
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Malformed success_criteria"):
        compile_evaluation_plan(scenario)
