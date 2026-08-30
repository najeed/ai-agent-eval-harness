"""
Branch coverage matrix for eval_runner/execution_ir.py.

Statement and branch coverage for Execution IR,
predicates, normalization, compilation, and semantic validation.
"""

from __future__ import annotations

import pytest

from eval_runner.execution_ir import (
    CompiledEvaluationPlan,
    CompiledOracle,
    EdgeIR,
    EdgeType,
    ExecutionIdentity,
    NodeIR,
    NodeVerdict,
    PlanValidationError,
    PredicateIR,
    WorkflowPlan,
    compile_evaluation_plan,
    compile_workflow,
    derive_oracle_id,
    evaluate_predicate,
    normalize_edge_type,
    resolve_predicate_path,
)


def _oracle(nid: str) -> dict:
    return {
        "id": nid,
        "success_criteria": [{"metric": "task_completion", "threshold": 1.0}],
    }


def test_node_verdict_matrix():
    # 1. Verification failed branch
    nv_fail = NodeVerdict(execution="success", verification="fail", policy="pass", parity="pass")
    assert nv_fail.overall == "verification_failed"
    assert not nv_fail.success

    # 2. to_dict with and without failed_assertion
    assert "failed_assertion" not in nv_fail.to_dict()
    nv_assert = NodeVerdict(
        execution="success",
        verification="fail",
        policy="pass",
        parity="pass",
        failed_assertion={"metric": "task_completion", "got": 0.0},
    )
    assert nv_assert.to_dict()["failed_assertion"] == {"metric": "task_completion", "got": 0.0}

    # 3. Conjunctive fallbacks
    nv_bad_verif = NodeVerdict(
        execution="success", verification="unknown", policy="pass", parity="pass"
    )
    assert nv_bad_verif.overall == "verification_failed"

    nv_bad_pol = NodeVerdict(
        execution="success", verification="pass", policy="unknown", parity="pass"
    )
    assert nv_bad_pol.overall == "policy_denied"

    nv_bad_par = NodeVerdict(
        execution="success", verification="pass", policy="pass", parity="unknown"
    )
    assert nv_bad_par.overall == "parity_failed"


def test_execution_identity_and_models():
    attempt_id = ExecutionIdentity.new_attempt_id()
    assert isinstance(attempt_id, str) and len(attempt_id) > 0

    scenario = {"workflow": {"nodes": [_oracle("a")]}}
    sc_hash = ExecutionIdentity.scenario_version_hash(scenario)
    assert sc_hash.startswith("sha3_256:")

    # EdgeIR.is_conditional
    e_seq = EdgeIR(edge_id="e1", from_node="a", to_node="b", type=EdgeType.SEQUENTIAL)
    e_err = EdgeIR(edge_id="e2", from_node="a", to_node="b", type=EdgeType.ERROR)
    e_to = EdgeIR(edge_id="e3", from_node="a", to_node="b", type=EdgeType.TIMEOUT)
    assert not e_seq.is_conditional
    assert e_err.is_conditional
    assert e_to.is_conditional

    # NodeIR timeout_seconds invalid handling
    n_neg = NodeIR(node_id="n1", definition={"timeout": -5.0})
    assert n_neg.timeout_seconds is None
    n_bad = NodeIR(node_id="n2", definition={"timeout": "not_a_float"})
    assert n_bad.timeout_seconds is None
    n_good = NodeIR(node_id="n3", definition={"timeout": 12.5})
    assert n_good.timeout_seconds == 12.5

    # CompiledOracle.to_dict
    co = CompiledOracle(
        oracle_id="o1",
        scenario_node_id="n1",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="task_completion",
    )
    assert co.to_dict()["oracle_id"] == "o1"

    # CompiledEvaluationPlan.to_dict
    ep = CompiledEvaluationPlan(oracles={"o1": co}, node_oracles={"n1": [co]})
    assert ep.to_dict()["total_oracles"] == 1
    assert ep.required_oracles_for_node("n1") == [co]

    # WorkflowPlan.required_incoming
    wp = WorkflowPlan(
        nodes={"a": NodeIR("a"), "b": NodeIR("b")},
        edges=[e_seq],
        entry_node_ids=["a"],
    )
    assert wp.required_incoming("b") == {"e1"}


def test_derive_oracle_id_and_evaluation_plan_compilation():
    # Custom kind fallback in derive_oracle_id
    assert derive_oracle_id("custom", "node1", {}) == "node1:custom:0"

    # compile_evaluation_plan with raw scenario without pre-compiled plan
    raw_scenario = {
        "workflow": {
            "nodes": [
                _oracle("n1"),
                "not_a_dict_skipped",
                {"no_id": True},
            ]
        }
    }
    ep = compile_evaluation_plan(raw_scenario)
    assert "n1:sc:task_completion" in ep.oracles

    # Malformed success_criteria
    bad_sc = {
        "workflow": {
            "nodes": [
                {"id": "n1", "success_criteria": ["not_a_dict"]},
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Malformed success_criteria"):
        compile_evaluation_plan(bad_sc)

    # Duplicate success_criteria oracle_id
    dup_sc = {
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "success_criteria": [
                        {"id": "dup1", "metric": "a"},
                        {"id": "dup1", "metric": "b"},
                    ],
                }
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Duplicate oracle_id"):
        compile_evaluation_plan(dup_sc)

    # Malformed state_hygiene rule
    bad_sh = {
        "workflow": {
            "nodes": [
                {"id": "n1", "state_hygiene": {"rules": ["not_a_dict"]}},
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Malformed state_hygiene rule"):
        compile_evaluation_plan(bad_sh)

    # Duplicate state_hygiene oracle_id
    dup_sh = {
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "state_hygiene": {
                        "rules": [
                            {"id": "dup_sh", "path": "p1"},
                            {"id": "dup_sh", "path": "p2"},
                        ]
                    },
                }
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Duplicate oracle_id"):
        compile_evaluation_plan(dup_sh)

    # Malformed expected_outcome
    bad_eo = {
        "workflow": {
            "nodes": [
                {"id": "n1", "expected_outcome": ["not_a_dict"]},
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Malformed expected_outcome"):
        compile_evaluation_plan(bad_eo)

    # Non-list assertions handling in compile_evaluation_plan
    non_list_assertions = {
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "success_criteria": "not_a_list",
                    "state_hygiene": {"rules": "not_a_list"},
                    "expected_outcome": "not_a_list",
                }
            ]
        }
    }
    ep_nl = compile_evaluation_plan(non_list_assertions)
    assert len(ep_nl.oracles) == 0

    # Single-node workflow with no edges (len(nodes_raw) == 1)
    single_node_plan = compile_workflow(
        {
            "workflow": {
                "nodes": [_oracle("solo")],
            }
        }
    )
    assert single_node_plan.entry_node_ids == ["solo"]

    # Duplicate expected_outcome oracle_id
    dup_eo = {
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "expected_outcome": [
                        {"id": "dup_eo", "target": "t1"},
                        {"id": "dup_eo", "target": "t2"},
                    ],
                }
            ]
        }
    }
    with pytest.raises(PlanValidationError, match="Duplicate oracle_id"):
        compile_evaluation_plan(dup_eo)


def test_predicate_normalization_and_evaluation_matrix():
    # normalize_edge_type None
    assert normalize_edge_type(None) == EdgeType.SEQUENTIAL
    assert normalize_edge_type("") == EdgeType.SEQUENTIAL

    # _normalize_predicate branches (None, bool, str, dict compound with all/any,
    # invalid all/any, and unsupported type)
    from eval_runner.execution_ir import _normalize_predicate

    assert _normalize_predicate(None) == PredicateIR(op="truthy")
    assert _normalize_predicate(True) == PredicateIR(op="eq", value=True)
    assert _normalize_predicate("abc.*") == PredicateIR(op="regex", value="abc.*")
    assert _normalize_predicate({"all": [True]}).op == "compound"
    with pytest.raises(PlanValidationError, match="must contain a list of clauses"):
        _normalize_predicate({"all": "not_a_list"})
    with pytest.raises(PlanValidationError, match="Unsupported predicate form"):
        _normalize_predicate(12345)

    # evaluate_predicate operators
    ctx = {
        "n": 5,
        "nested": {"key": "value"},
        "items": [1, 2, 3],
        "state": {"s_val": 42, "deep": {"v": 99}},
    }

    # gt
    p_gt_true = PredicateIR(op="gt", path="n", value=3)
    p_gt_false = PredicateIR(op="gt", path="n", value=10)
    assert evaluate_predicate(p_gt_true, ctx)[0] is True
    assert evaluate_predicate(p_gt_false, ctx)[0] is False

    # lte
    p_lte_true = PredicateIR(op="lte", path="n", value=5)
    p_lte_false = PredicateIR(op="lte", path="n", value=4)
    assert evaluate_predicate(p_lte_true, ctx)[0] is True
    assert evaluate_predicate(p_lte_false, ctx)[0] is False

    # contains (string substring)
    p_cont_str = PredicateIR(op="contains", path="nested.key", value="AL")
    assert evaluate_predicate(p_cont_str, ctx)[0] is True

    # not_exists
    p_nex_true = PredicateIR(op="not_exists", path="missing_key")
    p_nex_false = PredicateIR(op="not_exists", path="n")
    assert evaluate_predicate(p_nex_true, ctx)[0] is True
    assert evaluate_predicate(p_nex_false, ctx)[0] is False

    # in
    p_in_true = PredicateIR(op="in", path="n", value=[1, 2, 5])
    p_in_single = PredicateIR(op="in", path="n", value=5)
    p_in_false = PredicateIR(op="in", path="n", value=[1, 2, 3])
    assert evaluate_predicate(p_in_true, ctx)[0] is True
    assert evaluate_predicate(p_in_single, ctx)[0] is True
    assert evaluate_predicate(p_in_false, ctx)[0] is False

    # regex
    p_re_true = PredicateIR(op="regex", path="nested.key", value="^val.*")
    p_re_false = PredicateIR(op="regex", path="nested.key", value="^xyz")
    assert evaluate_predicate(p_re_true, ctx)[0] is True
    assert evaluate_predicate(p_re_false, ctx)[0] is False

    # Exception fallback (TypeError / ValueError)
    p_err = PredicateIR(op="gt", path="nested.key", value="unparseable_number")
    assert evaluate_predicate(p_err, ctx)[0] is False

    # Unsupported unknown op fallback
    p_unk = PredicateIR(op="unknown_unsupported_op", path="n", value=5)
    assert evaluate_predicate(p_unk, ctx)[0] is False

    # resolve_predicate_path fallback to state with dotted path not in top-level context
    assert resolve_predicate_path(ctx, "deep.v") == 99
    assert resolve_predicate_path(ctx, "s_val") == 42


def test_compile_workflow_validation_branches():
    # 1. Invalid or falsy workflow container
    with pytest.raises(PlanValidationError, match="workflow must be a dict or list"):
        compile_workflow({"workflow": 12345})
    with pytest.raises(PlanValidationError, match="Workflow contains no executable nodes"):
        compile_workflow({"workflow": None})

    # 2. Empty nodes
    with pytest.raises(PlanValidationError, match="Workflow contains no executable nodes"):
        compile_workflow({"workflow": {"nodes": []}})

    # 3. Duplicate node id
    with pytest.raises(PlanValidationError, match="Duplicate workflow node id"):
        compile_workflow({"workflow": {"nodes": [_oracle("n1"), _oracle("n1")]}})

    # 4. Missing edge endpoint
    with pytest.raises(PlanValidationError, match="missing endpoint"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [_oracle("n1"), _oracle("n2")],
                    "edges": [{"from": "n1"}],
                }
            }
        )

    # 5. Unknown target node in edge
    with pytest.raises(PlanValidationError, match="references unknown target node"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [_oracle("n1")],
                    "edges": [{"from": "n1", "to": "unknown_target"}],
                }
            }
        )

    # 6. Sequential edge with predicate coerced to condition + invalid priority string fallback
    plan_seq_pred = compile_workflow(
        {
            "workflow": {
                "nodes": [_oracle("n1"), _oracle("n2")],
                "edges": [
                    {
                        "from": "n1",
                        "to": "n2",
                        "type": "sequential",
                        "condition": {"op": "truthy"},
                        "priority": "invalid_int_defaults_to_100",
                    }
                ],
            }
        }
    )
    assert plan_seq_pred.edges[0].type == EdgeType.CONDITION
    assert plan_seq_pred.edges[0].priority == 100

    # 7. String entry_nodes
    plan_str_entry = compile_workflow(
        {
            "workflow": {
                "entry_nodes": "n1",
                "nodes": [_oracle("n1"), _oracle("n2")],
                "edges": [{"from": "n1", "to": "n2"}],
            }
        }
    )
    assert plan_str_entry.entry_node_ids == ["n1"]

    # 8. Node-level entry: true flag
    plan_node_entry = compile_workflow(
        {
            "workflow": {
                "nodes": [
                    {**_oracle("n1"), "entry": True},
                    _oracle("n2"),
                ],
                "edges": [{"from": "n1", "to": "n2"}],
            }
        }
    )
    assert plan_node_entry.entry_node_ids == ["n1"]

    # 9. entry_nodes referencing unknown node
    with pytest.raises(PlanValidationError, match="entry_nodes reference unknown"):
        compile_workflow(
            {
                "workflow": {
                    "entry_nodes": ["non_existent"],
                    "nodes": [_oracle("n1")],
                }
            }
        )

    # 10. Unknown failure_policy
    with pytest.raises(PlanValidationError, match="Unknown failure_policy"):
        compile_workflow(
            {
                "failure_policy": "invalid_policy_name",
                "workflow": {"nodes": [_oracle("n1")]},
            }
        )

    # 11. Workflow with no terminal node (pure cycle with entry_nodes declared)
    with pytest.raises(PlanValidationError, match="Workflow has no terminal node"):
        compile_workflow(
            {
                "workflow": {
                    "entry_nodes": ["n1"],
                    "nodes": [
                        {**_oracle("n1"), "max_visitations": 5},
                        {**_oracle("n2"), "max_visitations": 5},
                    ],
                    "edges": [
                        {"from": "n1", "to": "n2", "type": "sequential"},
                        {"from": "n2", "to": "n1", "type": "sequential"},
                    ],
                }
            }
        )

    # 12. Mixed sequential and conditional edges without default
    with pytest.raises(PlanValidationError, match="alongside conditional edges without 'default'"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [_oracle("n1"), _oracle("n2"), _oracle("n3")],
                    "edges": [
                        {"from": "n1", "to": "n2", "type": "sequential"},
                        {
                            "from": "n1",
                            "to": "n3",
                            "type": "condition",
                            "condition": {"op": "truthy"},
                        },
                    ],
                }
            }
        )

    # 13. Invalid join spec on node (e.g. invalid join.n integer)
    with pytest.raises(PlanValidationError, match="Join cardinality exceeds incoming degree"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        _oracle("n1"),
                        _oracle("n2"),
                        {**_oracle("n3"), "join": {"mode": "all", "n": "not_an_int"}},
                    ],
                    "edges": [
                        {"from": "n1", "to": "n3", "type": "parallel"},
                        {"from": "n2", "to": "n3", "type": "parallel"},
                    ],
                    "entry_nodes": ["n1", "n2"],
                }
            }
        )
