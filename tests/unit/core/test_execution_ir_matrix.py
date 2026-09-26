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
    OracleResult,
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

    # Duplicate expected_outcome oracle_id when explicit ID is identical
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

    # Multi-assertion on identical target without explicit IDs compiles successfully
    # with indexed oracle IDs
    multi_target_eo = {
        "workflow": {
            "nodes": [
                {
                    "id": "eval_node",
                    "expected_outcome": [
                        {"target": "message", "expected": "denied", "mode": "regex"},
                        {"target": "message", "expected": "notified", "mode": "regex"},
                    ],
                }
            ]
        }
    }
    plan_multi = compile_evaluation_plan(multi_target_eo)
    assert "eval_node:parity:message" in plan_multi.oracles
    assert "eval_node:parity:message:1" in plan_multi.oracles


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


def test_parse_oracle_requiredness_validation_branches():
    from eval_runner.execution_ir import _validate_oracle_requiredness

    # 1. Non-string requiredness
    with pytest.raises(PlanValidationError, match="'requiredness' must be a string"):
        _validate_oracle_requiredness({"requiredness": 123}, "test_ctx")

    # 2. Invalid requiredness enum
    with pytest.raises(PlanValidationError, match="Invalid requiredness 'SUPER_MANDATORY'"):
        _validate_oracle_requiredness({"requiredness": "SUPER_MANDATORY"}, "test_ctx")

    # 3. Inconsistent: required=True but requiredness=OPTIONAL
    with pytest.raises(
        PlanValidationError, match="'required=True' contradicts 'requiredness=OPTIONAL'"
    ):
        _validate_oracle_requiredness({"required": True, "requiredness": "OPTIONAL"}, "test_ctx")

    # 4. Inconsistent: required=False but requiredness=REQUIRED
    with pytest.raises(
        PlanValidationError, match="'required=False' contradicts 'requiredness=REQUIRED'"
    ):
        _validate_oracle_requiredness({"required": False, "requiredness": "REQUIRED"}, "test_ctx")


def test_evaluate_predicate_error_and_strict_modes():
    from eval_runner.execution_ir import PredicateEvaluationError, PredicateIR, evaluate_predicate

    # gt with None actual in strict mode
    p_gt_null_act = PredicateIR(op="gt", path="missing_key", value=10)
    with pytest.raises(PredicateEvaluationError, match="resolved to None"):
        evaluate_predicate(p_gt_null_act, {}, strict=True)

    # gt with None value in strict mode
    p_gt_null_val = PredicateIR(op="gt", path="val", value=None)
    with pytest.raises(PredicateEvaluationError, match="expected value is None"):
        evaluate_predicate(p_gt_null_val, {"val": 10}, strict=True)

    # contains with None actual in strict mode
    p_contains_null = PredicateIR(op="contains", path="missing", value="abc")
    with pytest.raises(PredicateEvaluationError, match="resolved to None"):
        evaluate_predicate(p_contains_null, {}, strict=True)

    # regex with None actual in strict mode
    p_regex_null = PredicateIR(op="regex", path="missing", value="^a")
    with pytest.raises(PredicateEvaluationError, match="resolved to None"):
        evaluate_predicate(p_regex_null, {}, strict=True)

    # non-strict mode suppresses PredicateEvaluationError
    assert evaluate_predicate(p_gt_null_act, {}, strict=False) == (False, None)

    # strict mode with TypeError/ValueError
    p_gt_type_err = PredicateIR(op="gt", path="val", value=5)
    with pytest.raises(PredicateEvaluationError, match="Evaluation error"):
        evaluate_predicate(p_gt_type_err, {"val": "not_a_number"}, strict=True)
    assert evaluate_predicate(p_gt_type_err, {"val": "not_a_number"}, strict=False) == (
        False,
        "not_a_number",
    )

    # strict mode with unsupported op
    p_unsupported = PredicateIR(op="unsupported_custom_op", path="val", value=1)
    with pytest.raises(PredicateEvaluationError, match="Unsupported predicate operator"):
        evaluate_predicate(p_unsupported, {"val": 1}, strict=True)
    assert evaluate_predicate(p_unsupported, {"val": 1}, strict=False) == (False, 1)


def test_node_verdict_overall_branch_matrix():
    assert NodeVerdict("failed", "pass", "pass", "pass").overall == "execution_failed"
    assert NodeVerdict("failed", "pass", "pass", "pass").success is False

    assert NodeVerdict("success", "invalid", "pass", "pass").overall == "evaluation_invalid"
    assert NodeVerdict("success", "pass", "denied", "pass").overall == "policy_denied"
    assert NodeVerdict("success", "pass", "pass", "fail").overall == "parity_failed"
    assert NodeVerdict("success", "unrecognized", "pass", "pass").overall == "verification_failed"
    assert NodeVerdict("success", "pass", "unrecognized", "pass").overall == "policy_denied"
    assert NodeVerdict("success", "pass", "pass", "unrecognized").overall == "parity_failed"
    assert NodeVerdict("success", "pass", "pass", "pass").overall == "success"
    assert (
        NodeVerdict(
            "success",
            "not_applicable",
            "not_applicable",
            "not_applicable",
        ).overall
        == "success"
    )
    verdict = NodeVerdict("success", "pass", "pass", "pass")
    d = verdict.to_dict()
    assert d["execution"] == "success"
    assert d["overall"] == "success"
    assert verdict.success is True


def test_execution_identity_instance_id_and_hashing():
    ident = ExecutionIdentity(
        evaluation_run_id="run_1",
        scenario_version_id="scen_1",
        case_id="case_1",
        attempt_id="att_1",
        attempt_number=2,
    )
    assert ident.execution_instance_id("node_alpha", iteration=1) == "node_alpha:attempt:2"
    assert ident.execution_instance_id("node_alpha", iteration=0) == "node_alpha:attempt:2"
    assert ident.execution_instance_id("node_alpha", iteration=3) == "node_alpha:attempt:2#it3"

    h = ident.scenario_version_hash({"id": "scen_1", "description": "test"})
    assert h.startswith("sha3_256:")


def test_predicate_ir_to_evidence_nested():
    child = PredicateIR(op="truthy", path="status", value=True)
    parent = PredicateIR(logic="all", clauses=(child,))
    ev = parent.to_evidence()
    assert ev == {
        "logic": "all",
        "clauses": [{"op": "truthy", "path": "status", "value": True}],
    }


def test_node_ir_properties_and_join_modes():
    node_def = NodeIR(node_id="n_def", definition={})
    assert node_def.timeout_seconds is None
    assert node_def.max_visitations > 0
    assert node_def.join_threshold is None

    node_bad_vis = NodeIR(node_id="n_bad_vis", definition={"max_visitations": "not_an_int"})
    assert node_bad_vis.max_visitations > 0

    node_bad_jt = NodeIR(node_id="n_bad_jt", definition={"join_threshold": "not_an_int"})
    assert node_bad_jt.join_threshold is None

    node_jt = NodeIR(node_id="n_jt", definition={"join_threshold": 3})
    mode, n = node_jt.join_spec({"e1", "e2", "e3", "e4"})
    assert mode == "n_of_m"
    assert n == 3

    node_any = NodeIR(node_id="n_any", definition={"join": "any"})
    mode_any, n_any = node_any.join_spec({"e1", "e2"})
    assert mode_any == "any"
    assert n_any == 1

    node_invalid_mode = NodeIR(node_id="n_inv", definition={"join": "invalid_mode_name"})
    with pytest.raises(PlanValidationError, match="unknown join mode 'invalid_mode_name'"):
        node_invalid_mode.join_spec({"e1"})


def test_oracle_result_to_dict():
    res = OracleResult(
        oracle_id="scen:node:sc:0",
        scenario_node_id="node_a",
        resolver="agentv.sc",
        requiredness="REQUIRED",
        outcome="PASS",
        expected=True,
        observed=True,
        evidence_refs=["ev_1"],
        error=None,
    )
    d = res.to_dict()
    assert d["oracle_id"] == "scen:node:sc:0"
    assert d["scenario_node_id"] == "node_a"
    assert d["resolver"] == "agentv.sc"
    assert d["outcome"] == "PASS"


def test_workflow_plan_step_budget():
    plan = compile_workflow(
        {
            "workflow": {
                "nodes": [
                    {"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    {"id": "n2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                ],
                "edges": [{"from": "n1", "to": "n2"}],
            }
        }
    )
    assert plan.step_budget >= 1


def test_derive_oracle_id_variations():
    assert (
        derive_oracle_id("hygiene", "node_x", {"path": "/var/log/test.log"})
        == "node_x:hygiene:/var/log/test.log"
    )
    assert derive_oracle_id("hygiene", "node_x", {}, idx=5) == "node_x:hygiene:5"

    assert (
        derive_oracle_id("parity", "node_x", {"target": "golden_truth"})
        == "node_x:parity:golden_truth"
    )
    assert derive_oracle_id("parity", "node_x", {}, idx=7) == "node_x:parity:7"


def test_compile_workflow_normalize_edge_type_invalid():
    with pytest.raises(PlanValidationError, match="Unknown edge type 'completely_unknown'"):
        normalize_edge_type("completely_unknown")


def test_compile_workflow_list_form_and_untyped_parallel():
    plan = compile_workflow(
        {
            "workflow": [
                {"id": "step_a", "success_criteria": [{"metric": "m", "threshold": 1}]},
                {"id": "step_b", "success_criteria": [{"metric": "m", "threshold": 1}]},
            ]
        }
    )
    assert len(plan.nodes) == 2
    assert len(plan.edges) == 1
    assert plan.edges[0].from_node == "step_a"
    assert plan.edges[0].to_node == "step_b"

    plan_parallel = compile_workflow(
        {
            "workflow": {
                "nodes": [
                    {"id": "root", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    {"id": "branch_1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    {"id": "branch_2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                ],
                "edges": [
                    {"from": "root", "to": "branch_1"},
                    {"from": "root", "to": "branch_2"},
                ],
            }
        }
    )
    assert any(e.type == EdgeType.PARALLEL for e in plan_parallel.edges)


def test_compile_workflow_unknown_source_edge():
    with pytest.raises(
        PlanValidationError, match="Edge references unknown source node: 'nonexistent'"
    ):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [{"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]}],
                    "edges": [{"from": "nonexistent", "to": "n1"}],
                }
            }
        )


def test_compile_workflow_multiple_source_nodes_ambiguous():
    with pytest.raises(PlanValidationError, match="Ambiguous workflow entry"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n3", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {"from": "n1", "to": "n3"},
                        {"from": "n2", "to": "n3"},
                    ],
                }
            }
        )


def test_compile_workflow_unreachable_node():
    with pytest.raises(PlanValidationError, match="Unreachable nodes from entry"):
        compile_workflow(
            {
                "workflow": {
                    "entry_nodes": ["n1"],
                    "nodes": [
                        {"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {
                            "id": "n3_unreachable",
                            "success_criteria": [{"metric": "m", "threshold": 1}],
                        },
                    ],
                    "edges": [{"from": "n1", "to": "n2"}],
                }
            }
        )


def test_compile_workflow_condition_edge_missing_predicate():
    with pytest.raises(PlanValidationError, match="requires a predicate"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [{"from": "n1", "to": "n2", "type": "condition"}],
                }
            }
        )


def test_compile_workflow_ambiguous_successors():
    with pytest.raises(PlanValidationError, match="multiple sequential edges declared"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n3", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {"from": "n1", "to": "n2", "type": "sequential"},
                        {"from": "n1", "to": "n3", "type": "sequential"},
                    ],
                }
            }
        )

    with pytest.raises(PlanValidationError, match="mixed sequential and parallel edges"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n3", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {"from": "n1", "to": "n2", "type": "sequential"},
                        {"from": "n1", "to": "n3", "type": "parallel"},
                    ],
                }
            }
        )

    with pytest.raises(PlanValidationError, match="mixed parallel and conditional edges"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "n1", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n2", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "n3", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {"from": "n1", "to": "n2", "type": "parallel"},
                        {
                            "from": "n1",
                            "to": "n3",
                            "type": "condition",
                            "predicate": {"path": "x", "op": "truthy"},
                        },
                    ],
                }
            }
        )


def test_compile_workflow_advanced_semantic_validations():
    with pytest.raises(PlanValidationError, match="Ambiguous fallback routing"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "a", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "b", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "c", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {"from": "a", "to": "b", "type": "default"},
                        {"from": "a", "to": "c", "type": "default"},
                    ],
                }
            }
        )

    with pytest.raises(PlanValidationError, match="Non-exclusive conditional routing"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "a", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "b", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "c", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {
                            "from": "a",
                            "to": "b",
                            "type": "condition",
                            "priority": 10,
                            "predicate": {"path": "x", "op": "truthy"},
                        },
                        {
                            "from": "a",
                            "to": "c",
                            "type": "condition",
                            "priority": 10,
                            "predicate": {"path": "y", "op": "truthy"},
                        },
                    ],
                }
            }
        )

    with pytest.raises(PlanValidationError, match="Join cardinality exceeds incoming degree"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "a", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {
                            "id": "b",
                            "join": {"mode": "n_of_m", "n": 3},
                            "success_criteria": [{"metric": "m", "threshold": 1}],
                        },
                    ],
                    "edges": [{"from": "a", "to": "b"}],
                }
            }
        )

    with pytest.raises(PlanValidationError, match="self-compensation"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [{"id": "a", "success_criteria": [{"metric": "m", "threshold": 1}]}],
                    "edges": [{"from": "a", "to": "a", "type": "compensation"}],
                }
            }
        )

    with pytest.raises(PlanValidationError, match="compensation originates from unreachable node"):
        compile_workflow(
            {
                "workflow": {
                    "entry_nodes": ["a"],
                    "nodes": [
                        {"id": "a", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "b", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {"id": "c", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {"from": "a", "to": "b"},
                        {"from": "c", "to": "a", "type": "compensation"},
                    ],
                }
            }
        )

    with pytest.raises(PlanValidationError, match="Loop nodes without explicit visitation budget"):
        compile_workflow(
            {
                "workflow": {
                    "entry_nodes": ["entry"],
                    "nodes": [
                        {"id": "entry", "success_criteria": [{"metric": "m", "threshold": 1}]},
                        {
                            "id": "a",
                            "max_visitations": 5,
                            "success_criteria": [{"metric": "m", "threshold": 1}],
                        },
                        {"id": "b", "success_criteria": [{"metric": "m", "threshold": 1}]},
                    ],
                    "edges": [
                        {"from": "entry", "to": "a"},
                        {"from": "a", "to": "b"},
                        {"from": "b", "to": "a"},
                    ],
                }
            }
        )


def test_compile_workflow_minimum_oracle_rule_violation():
    with pytest.raises(PlanValidationError, match="Minimum-oracle rule violated"):
        compile_workflow({"workflow": [{"id": "empty_node"}]})


def test_resolve_predicate_path_empty_or_none():
    data = {"system_state": "healthy"}
    assert resolve_predicate_path(data, "") == data
    assert resolve_predicate_path(data, None) == data


def test_evaluate_predicate_all_operators_exhaustive():
    p_comp_all = PredicateIR(
        op="compound",
        logic="all",
        clauses=(
            PredicateIR(op="eq", path="k1", value="v1"),
            PredicateIR(op="eq", path="k2", value="v2"),
        ),
    )
    assert evaluate_predicate(p_comp_all, {"k1": "v1", "k2": "v2"})[0] is True
    assert evaluate_predicate(p_comp_all, {"k1": "v1", "k2": "mismatch"})[0] is False

    p_comp_any = PredicateIR(
        op="compound",
        logic="any",
        clauses=(
            PredicateIR(op="eq", path="k1", value="v1"),
            PredicateIR(op="eq", path="k2", value="v2"),
        ),
    )
    assert evaluate_predicate(p_comp_any, {"k1": "v1", "k2": "mismatch"})[0] is True
    assert evaluate_predicate(p_comp_any, {"k1": "other", "k2": "other"})[0] is False

    assert evaluate_predicate(PredicateIR(op="eq", path="x", value=42), {"x": 42}) == (True, 42)
    assert evaluate_predicate(PredicateIR(op="eq", path="x", value=42), {"x": 43}) == (False, 43)

    assert evaluate_predicate(PredicateIR(op="ne", path="x", value=42), {"x": 43}) == (True, 43)
    assert evaluate_predicate(PredicateIR(op="ne", path="x", value=42), {"x": 42}) == (False, 42)

    assert evaluate_predicate(PredicateIR(op="gte", path="x", value=10), {"x": 10}) == (True, 10)
    assert evaluate_predicate(PredicateIR(op="gte", path="x", value=10), {"x": 11}) == (True, 11)
    assert evaluate_predicate(PredicateIR(op="gte", path="x", value=10), {"x": 9}) == (False, 9)

    assert evaluate_predicate(PredicateIR(op="lt", path="x", value=20), {"x": 19}) == (True, 19)
    assert evaluate_predicate(PredicateIR(op="lt", path="x", value=20), {"x": 20}) == (False, 20)

    assert evaluate_predicate(
        PredicateIR(op="contains", path="seq", value="target"), {"seq": ["a", "target", "b"]}
    ) == (True, ["a", "target", "b"])
    assert evaluate_predicate(
        PredicateIR(op="contains", path="seq", value="target"), {"seq": ["a", "b"]}
    ) == (False, ["a", "b"])
    assert evaluate_predicate(
        PredicateIR(op="contains", path="text", value="needle"), {"text": "A Needle in Haystack"}
    ) == (True, "A Needle in Haystack")

    assert evaluate_predicate(PredicateIR(op="exists", path="opt"), {"opt": "present"}) == (
        True,
        "present",
    )
    assert evaluate_predicate(PredicateIR(op="exists", path="opt"), {}) == (False, None)

    assert evaluate_predicate(PredicateIR(op="truthy", path="flag"), {"flag": True}) == (True, True)
    assert evaluate_predicate(PredicateIR(op="truthy", path="flag"), {"flag": False}) == (
        False,
        False,
    )
