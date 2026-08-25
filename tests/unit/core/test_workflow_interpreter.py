"""
Unit tests for the Canonical Execution IR + Workflow Interpreter.

Covers the P0 kernel contract:
  - real ready-set scheduling (not topological linearization)
  - typed edge selection with evaluated-predicate evidence
  - bounded loops, join convergence, parallel fan-out
  - NODE_FAILED != WORKFLOW_FAILED under graph failure policies
"""

from __future__ import annotations

import asyncio
import time

import pytest

from eval_runner.execution_ir import (
    EdgeType,
    ExecutionIdentity,
    PlanValidationError,
    compile_workflow,
    evaluate_predicate,
)
from eval_runner.workflow_interpreter import WorkflowInterpreter


def _identity(attempt_number: int = 1) -> ExecutionIdentity:
    return ExecutionIdentity(
        evaluation_run_id="run-test",
        scenario_version_id="sha3_256:test",
        case_id="case",
        attempt_id="att123",
        attempt_number=attempt_number,
    )


def _plan(scenario: dict):
    """
    Compiles the scenario via the authoritative compiler.

    [A2] The minimum-oracle rule is an evaluation concern; these kernel
    semantics tests use deliberately bare nodes, so a trivially-satisfiable
    oracle is injected into any node that lacks one.

    [P0-11] These tests DECLARE their entry node explicitly (the first
    declared node) — declaration-order defaults are no longer inferred.
    """
    import copy as _copy

    scenario = _copy.deepcopy(scenario)
    workflow = scenario.get("workflow")
    if isinstance(workflow, dict):
        nodes = workflow.setdefault("nodes", [])
        if not workflow.get("entry_nodes") and nodes:
            workflow["entry_nodes"] = [str(nodes[0]["id"])]
    elif isinstance(workflow, list):
        nodes = workflow
    else:
        nodes = []
    for node in nodes:
        if isinstance(node, dict) and not any(
            node.get(key) for key in ("success_criteria", "state_hygiene", "expected_outcome")
        ):
            node["success_criteria"] = [{"metric": "task_completion", "threshold": 1.0}]
    return compile_workflow(scenario)


async def _run(plan, executor, state=None, failure_policy=None):
    async def ctx_provider():
        return {"state": state or {}}

    interp = WorkflowInterpreter(
        plan,
        _identity(),
        event_bus=None,
        context_provider=ctx_provider,
    )
    return await interp.run(executor)


# ---------------------------------------------------------------------------
# IR compilation
# ---------------------------------------------------------------------------


def test_compile_rejects_unknown_edge_type():
    with pytest.raises(PlanValidationError, match="Unknown edge type"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [{"id": "a"}, {"id": "b"}],
                    "edges": [{"from": "a", "to": "b", "type": "teleport"}],
                }
            }
        )


def test_compile_rejects_dangling_edge():
    with pytest.raises(PlanValidationError, match="unknown source node"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [{"id": "a"}],
                    "edges": [{"from": "ghost", "to": "a"}],
                }
            }
        )


def test_compile_legacy_list_form_becomes_explicit_chain():
    oracle = [{"metric": "task_completion", "threshold": 1.0}]
    plan = compile_workflow(
        {
            "workflow": [
                {"id": "a", "success_criteria": oracle},
                {"id": "b", "success_criteria": oracle},
                {"id": "c", "success_criteria": oracle},
            ]
        }
    )
    assert plan.legacy_linearized
    assert [e.from_node for e in plan.edges] == ["a", "b"]
    assert [e.to_node for e in plan.edges] == ["b", "c"]


def test_compile_rejects_list_form_without_oracles():
    # [A2] Even legacy list-form workflows enforce the minimum-oracle rule.
    with pytest.raises(PlanValidationError, match="NO_ASSERTIONS"):
        compile_workflow({"workflow": [{"id": "a"}, {"id": "b"}]})


def test_compile_rejects_ambiguous_multi_source_without_entry_declaration():
    # [P0-11] Declaration order must never decide control flow: two source
    # nodes without an explicit entry declaration are a plan error.
    oracle = [{"metric": "task_completion", "threshold": 1.0}]
    with pytest.raises(PlanValidationError, match="Ambiguous workflow entry"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [
                        {"id": "x", "success_criteria": oracle},
                        {"id": "y", "success_criteria": oracle},
                        {"id": "z", "success_criteria": oracle},
                    ],
                    "edges": [{"from": "x", "to": "z"}, {"from": "y", "to": "z"}],
                }
            }
        )


def test_compile_entry_declaration_wins_over_declared_order():
    # [P0-11] The declared entry is authoritative even when it is not first.
    oracle = [{"metric": "task_completion", "threshold": 1.0}]
    plan = compile_workflow(
        {
            "workflow": {
                "entry_nodes": ["second"],
                "nodes": [
                    {"id": "first", "success_criteria": oracle},
                    {"id": "second", "success_criteria": oracle},
                ],
                "edges": [{"from": "second", "to": "first"}],
            }
        }
    )
    assert plan.entry_node_ids == ["second"]
    assert plan.nodes["second"].is_entry
    assert not plan.nodes["first"].is_entry


def test_compile_compensation_backedge_does_not_reroot_workflow():
    # [P0-11] A compensation (undo) edge into the canonical start never makes
    # another node the entry.
    oracle = [{"metric": "task_completion", "threshold": 1.0}]
    plan = compile_workflow(
        {
            "failure_policy": "compensate_then_fail",
            "workflow": {
                "nodes": [
                    {"id": "start", "success_criteria": oracle},
                    {"id": "worker", "success_criteria": oracle},
                ],
                "edges": [
                    {"from": "start", "to": "worker"},
                    {"from": "worker", "to": "start", "type": "compensation"},
                ],
            },
        }
    )
    assert plan.entry_node_ids == ["start"]


def test_conditional_edge_without_predicate_is_invalid():
    with pytest.raises(PlanValidationError, match="requires a predicate"):
        compile_workflow(
            {
                "workflow": {
                    "nodes": [{"id": "a"}, {"id": "b"}],
                    "edges": [{"from": "a", "to": "b", "type": "condition"}],
                }
            }
        )


def test_predicate_evaluation_operators():
    from eval_runner.execution_ir import PredicateIR

    ctx = {"state": {"order": {"status": "approved"}, "n": 3}, "tools_used": ["t1"]}
    assert evaluate_predicate(_p("eq", "state.order.status", "approved"), ctx)[0] is True
    assert evaluate_predicate(_p("ne", "state.order.status", "denied"), ctx)[0] is True
    assert evaluate_predicate(_p("gte", "state.n", 3), ctx)[0] is True
    assert evaluate_predicate(_p("contains", "tools_used", "t1"), ctx)[0] is True
    compound = PredicateIR(
        op="compound",
        logic="all",
        clauses=(
            _p("eq", "state.order.status", "approved"),
            _p("lt", "state.n", 2),
        ),
    )
    passed, observed = evaluate_predicate(compound, ctx)
    assert passed is False
    assert isinstance(observed, list)
    any_compound = PredicateIR(op="compound", logic="any", clauses=compound.clauses)
    passed_any, _ = evaluate_predicate(any_compound, ctx)
    assert passed_any is True


def _p(op, path, value):
    from eval_runner.execution_ir import PredicateIR

    return PredicateIR(op=op, path=path, value=value)


# ---------------------------------------------------------------------------
# Branch selection + evidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_edge_selected_with_predicate_evidence():
    scenario = {
        "workflow": {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {
                    "id": "e_ab",
                    "from": "a",
                    "to": "b",
                    "type": "condition",
                    "condition": {"op": "eq", "path": "state.flag", "value": True},
                },
                {"id": "e_ac", "from": "a", "to": "c", "type": "default"},
            ],
        }
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        return {"task_id": node_ir.node_id, "status": "success"}

    results, outcome = await _run(plan, executor, state={"flag": True})

    assert outcome.success
    executed = [r["task_id"] for r in results]
    assert executed == ["a", "b"]  # branch c NOT taken
    t = outcome.transitions[0]
    assert t.selected_edge_id == "e_ab"
    assert t.edge_type == EdgeType.CONDITION.value
    assert t.transition_reason == "predicate_matched"
    assert t.evaluated_predicate == {"op": "eq", "path": "state.flag", "value": True}
    assert outcome.skipped_node_ids == ["c"]


@pytest.mark.asyncio
async def test_default_edge_fallback_when_no_condition_matches():
    scenario = {
        "workflow": {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {
                    "from": "a",
                    "to": "b",
                    "type": "condition",
                    "condition": {"op": "exists", "path": "state.missing_key"},
                },
                {"id": "e_def", "from": "a", "to": "c", "type": "default"},
            ],
        }
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        return {"task_id": node_ir.node_id, "status": "success"}

    results, outcome = await _run(plan, executor, state={})
    assert outcome.success
    assert [r["task_id"] for r in results] == ["a", "c"]
    assert outcome.transitions[0].transition_reason == "default_fallback"
    assert outcome.transitions[0].selected_edge_id == "e_def"


# ---------------------------------------------------------------------------
# Loops / retries / joins / parallelism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_edge_is_bounded_and_terminates():
    scenario = {
        "workflow": {
            "nodes": [
                {"id": "poll", "max_visitations": 4},
                {"id": "done"},
            ],
            "edges": [
                {
                    "from": "poll",
                    "to": "poll",
                    "type": "retry",
                    "condition": {"op": "lt", "path": "state.count", "value": 2},
                },
                {
                    "from": "poll",
                    "to": "done",
                    "type": "condition",
                    "condition": {"op": "gte", "path": "state.count", "value": 2},
                },
            ],
        }
    }
    plan = _plan(scenario)

    shared_state = {"count": 0}

    async def executor(node_ir, exec_id, parent):
        if node_ir.node_id == "poll":
            shared_state["count"] += 1
        return {"task_id": node_ir.node_id, "status": "success"}

    results, outcome = await _run(plan, executor, state=shared_state)

    assert outcome.success
    poll_runs = [r for r in results if r["task_id"] == "poll"]
    assert len(poll_runs) == 2  # count reaches 2 on second run -> exits to done
    loop_transitions = [t for t in outcome.transitions if t.transition_reason == "loop_iteration"]
    exit_transitions = [
        t
        for t in outcome.transitions
        if t.transition_reason == "predicate_matched" and t.selected_edge_id.endswith("->done")
    ]
    assert len(loop_transitions) == 1
    assert len(exit_transitions) >= 1


@pytest.mark.asyncio
async def test_join_waits_for_all_incoming_branches():
    scenario = {
        "workflow": {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
            "edges": [
                {"from": "a", "to": "b", "type": "parallel"},
                {"from": "a", "to": "c", "type": "parallel"},
                {"from": "b", "to": "d"},
                {"from": "c", "to": "d"},
            ],
        }
    }
    plan = _plan(scenario)
    order: list[str] = []

    async def executor(node_ir, exec_id, parent):
        order.append(f"{node_ir.node_id}:{exec_id}")
        return {"task_id": node_ir.node_id, "status": "success"}

    results, outcome = await _run(plan, executor)

    assert outcome.success
    d_runs = [r for r in results if r["task_id"] == "d"]
    assert len(d_runs) == 1  # AND-join: executes once after both branches
    names = [o.split(":")[0] for o in order]
    assert names.index("d") > names.index("b")
    assert names.index("d") > names.index("c")
    join_edges = [t for t in outcome.transitions if t.edge_type == EdgeType.PARALLEL.value]
    assert len(join_edges) == 2


@pytest.mark.asyncio
async def test_parallel_fanout_executes_both_branches():
    scenario = {
        "workflow": {
            "nodes": [{"id": "root"}, {"id": "l"}, {"id": "r"}],
            "edges": [
                {"from": "root", "to": "l", "type": "parallel"},
                {"from": "root", "to": "r", "type": "parallel"},
            ],
        }
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        return {"task_id": node_ir.node_id, "status": "success"}

    results, outcome = await _run(plan, executor)
    assert sorted(r["task_id"] for r in results) == ["l", "r", "root"]
    fanout = [t for t in outcome.transitions if t.transition_reason == "parallel_fanout"]
    assert len(fanout) == 2


# ---------------------------------------------------------------------------
# Failure semantics: NODE_FAILED != WORKFLOW_FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_handler_edge_prevents_workflow_failure():
    scenario = {
        "workflow": {
            "nodes": [{"id": "risky"}, {"id": "handler"}, {"id": "finalize"}],
            "edges": [
                {"id": "e_rh", "from": "risky", "to": "handler", "type": "error"},
                {"from": "handler", "to": "finalize"},
            ],
        },
        "failure_policy": "fail_fast",
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        status = "failure" if node_ir.node_id == "risky" else "success"
        return {"task_id": node_ir.node_id, "status": status}

    results, outcome = await _run(plan, executor)

    # Node failed, but the graph routed through the error handler to a terminal.
    assert "risky" in outcome.failed_node_ids
    assert outcome.status.name.startswith("COMPLETED") or outcome.success
    executed = [r["task_id"] for r in results]
    assert executed == ["risky", "handler", "finalize"]
    err_edge = outcome.transitions[0]
    assert err_edge.edge_type == EdgeType.ERROR.value
    assert err_edge.transition_reason == "error_handler"


@pytest.mark.asyncio
async def test_unhandled_failure_under_fail_fast_stops_workflow():
    scenario = {
        "failure_policy": "fail_fast",
        "workflow": {
            "nodes": [{"id": "boom"}, {"id": "never"}],
            "edges": [{"from": "boom", "to": "never"}],
        },
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        status = "failure" if node_ir.node_id == "boom" else "success"
        return {"task_id": node_ir.node_id, "status": status}

    results, outcome = await _run(plan, executor)
    assert not outcome.success
    assert outcome.status.value == "workflow_failed"
    assert "boom" in outcome.failed_node_ids
    assert [r["task_id"] for r in results] == ["boom"]  # never never ran


@pytest.mark.asyncio
async def test_continue_independent_policy_executes_sibling_branch():
    scenario = {
        "failure_policy": "continue_independent",
        "workflow": {
            "nodes": [{"id": "root"}, {"id": "boom"}, {"id": "sibling"}],
            "edges": [
                {"from": "root", "to": "boom", "type": "parallel"},
                {"from": "root", "to": "sibling", "type": "parallel"},
            ],
        },
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        status = "failure" if node_ir.node_id == "boom" else "success"
        return {"task_id": node_ir.node_id, "status": status}

    results, outcome = await _run(plan, executor)
    executed = [r["task_id"] for r in results]
    assert "sibling" in executed  # independent sibling branch still executed
    assert not outcome.success  # but unhandled failure fails the verdict
    assert outcome.failed_node_ids == ["boom"]


@pytest.mark.asyncio
async def test_fail_fast_policy_halts_sibling_branches():
    scenario = {
        "failure_policy": "fail_fast",
        "workflow": {
            "nodes": [{"id": "root"}, {"id": "boom"}, {"id": "sibling"}],
            "edges": [
                {"from": "root", "to": "boom", "type": "parallel"},
                {"from": "root", "to": "sibling", "type": "parallel"},
            ],
        },
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        status = "failure" if node_ir.node_id == "boom" else "success"
        return {"task_id": node_ir.node_id, "status": status}

    results, outcome = await _run(plan, executor)
    executed = [r["task_id"] for r in results]
    # [P0-3] boom and sibling are ONE concurrent wave: both execute (an
    # in-flight wave cannot be un-run), but fail-fast guarantees the verdict
    # fails and NO downstream wave is ever scheduled.
    assert "sibling" in executed
    assert not outcome.success
    assert outcome.failed_node_ids == ["boom"]
    assert outcome.status.value == "workflow_failed"


@pytest.mark.asyncio
async def test_retry_edge_on_failure_until_success():
    scenario = {
        "workflow": {
            "nodes": [{"id": "flaky", "max_visitations": 5}],
            "edges": [
                {"id": "e_self", "from": "flaky", "to": "flaky", "type": "retry"},
            ],
        }
    }
    plan = _plan(scenario)
    calls = {"n": 0}

    async def executor(node_ir, exec_id, parent):
        calls["n"] += 1
        status = "success" if calls["n"] >= 3 else "failure"
        return {"task_id": node_ir.node_id, "status": status}

    results, outcome = await _run(plan, executor)
    assert calls["n"] == 3
    retry_transitions = [t for t in outcome.transitions if t.transition_reason == "retry"]
    assert len(retry_transitions) == 2
    assert outcome.success


@pytest.mark.asyncio
async def test_compensation_then_fail_runs_compensation_target():
    scenario = {
        "failure_policy": "compensate_then_fail",
        "workflow": {
            "nodes": [{"id": "charge"}, {"id": "refund"}],
            "edges": [{"id": "e_comp", "from": "charge", "to": "refund", "type": "compensation"}],
        },
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        status = "failure" if node_ir.node_id == "charge" else "success"
        return {"task_id": node_ir.node_id, "status": status}

    results, outcome = await _run(plan, executor)
    executed = [r["task_id"] for r in results]
    assert executed == ["charge", "refund"]  # compensation ran despite fail-fast-like policy
    assert not outcome.success
    comp = outcome.transitions[0]
    assert comp.edge_type == EdgeType.COMPENSATION.value
    assert comp.transition_reason == "compensation"


@pytest.mark.asyncio
async def test_step_budget_guard_terminates_runaway_loop():
    scenario = {
        "workflow": {
            "nodes": [{"id": "loop", "max_visitations": 10**6}],
            "edges": [
                {
                    "from": "loop",
                    "to": "loop",
                    "type": "retry",
                    "condition": {"op": "truthy"},
                },
            ],
        }
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        return {"task_id": node_ir.node_id, "status": "success"}

    results, outcome = await _run(plan, executor)
    assert outcome.status.value == "workflow_failed"
    assert "Step budget exceeded" in outcome.reason


# ---------------------------------------------------------------------------
# Identity contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_instance_ids_carry_iteration_qualifier():
    scenario = {
        "workflow": {
            "nodes": [{"id": "n", "max_visitations": 5}, {"id": "m"}],
            "edges": [
                {
                    "from": "n",
                    "to": "n",
                    "type": "retry",
                    "condition": {"op": "lt", "path": "state.count", "value": 2},
                },
                {"from": "n", "to": "m"},
            ],
        }
    }
    plan = _plan(scenario)
    visits = {"count": 0}

    async def executor(node_ir, exec_id, parent):
        if node_ir.node_id == "n":
            visits["count"] += 1
        return {"task_id": node_ir.node_id, "status": "success"}

    interp = WorkflowInterpreter(
        plan,
        _identity(attempt_number=7),
        event_bus=None,
        context_provider=lambda: _async_ctx(visits),
    )
    results, outcome = await interp.run(executor)

    n_ids = [
        rec.execution_instance_id for rec in outcome.node_executions if rec.scenario_node_id == "n"
    ]
    m_ids = [
        rec.execution_instance_id for rec in outcome.node_executions if rec.scenario_node_id == "m"
    ]
    # First visitation keeps the legacy-compatible base form; later iterations qualify.
    assert n_ids == ["n:attempt:7", "n:attempt:7#it2"]
    assert m_ids == ["m:attempt:7"]
    assert outcome.success


async def _async_ctx(state):
    return {"state": state}


# ---------------------------------------------------------------------------
# [A7] TIMEOUT edge — executable contract (closes per-EdgeType coverage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_edge_routes_failure_to_handler():
    scenario = {
        "workflow": {
            "nodes": [{"id": "slow"}, {"id": "timeout_handler"}, {"id": "finalize"}],
            "edges": [
                {"id": "e_to", "from": "slow", "to": "timeout_handler", "type": "timeout"},
                {"from": "timeout_handler", "to": "finalize"},
            ],
        },
        "failure_policy": "fail_fast",
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        status = "failure" if node_ir.node_id == "slow" else "success"
        result = {"task_id": node_ir.node_id, "status": status}
        if status == "failure":
            result["failure_class"] = "TIMEOUT"
        return result

    results, outcome = await _run(plan, executor)

    # NODE_FAILED != WORKFLOW_FAILED: the timeout route reaches a terminal.
    assert outcome.success
    assert outcome.status.value == "workflow_completed"
    executed = [r["task_id"] for r in results]
    assert executed == ["slow", "timeout_handler", "finalize"]

    transition = outcome.transitions[0]
    assert transition.edge_type == EdgeType.TIMEOUT.value
    assert transition.transition_reason == "timeout_route"
    assert "slow" in outcome.failed_node_ids


@pytest.mark.asyncio
async def test_timeout_edge_with_failing_predicate_is_not_taken():
    scenario = {
        "workflow": {
            "nodes": [{"id": "slow"}, {"id": "guarded_handler"}],
            "edges": [
                {
                    "id": "e_to",
                    "from": "slow",
                    "to": "guarded_handler",
                    "type": "timeout",
                    "condition": {"op": "eq", "path": "state.armed", "value": True},
                },
            ],
        },
        "failure_policy": "fail_fast",
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        return {"task_id": node_ir.node_id, "status": "failure"}

    # state.armed is False -> the guarded timeout route must NOT fire; the
    # failure is unhandled and the workflow fails.
    results, outcome = await _run(plan, executor, state={"armed": False})
    assert not outcome.success
    assert outcome.status.value == "workflow_failed"
    assert all(t.transition_reason != "timeout_route" for t in outcome.transitions)


@pytest.mark.asyncio
async def test_error_edge_takes_priority_over_timeout_edge():
    scenario = {
        "workflow": {
            "nodes": [{"id": "boom"}, {"id": "error_handler"}, {"id": "timeout_handler"}],
            "edges": [
                {"from": "boom", "to": "error_handler", "type": "error"},
                {"from": "boom", "to": "timeout_handler", "type": "timeout"},
            ],
        },
        "failure_policy": "fail_fast",
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        return {"task_id": node_ir.node_id, "status": "failure"}

    results, outcome = await _run(plan, executor)

    # Routing precedence: error edges win over timeout edges on plain failure.
    reasons = [t.transition_reason for t in outcome.transitions]
    assert "error_handler" in reasons
    assert "timeout_route" not in reasons


# ---------------------------------------------------------------------------
# Quick-win kernel contracts
# ---------------------------------------------------------------------------


def test_join_rejects_cross_iteration_tokens():
    """[P0-4] A join consumes ONLY tokens sharing one (lineage, iteration) key.

    Direct _try_join probe: an e2 token produced by loop iteration 9 can never
    complete the AND-join left half-open by e1's iteration-1 sibling.
    """
    from eval_runner.workflow_interpreter import ExecutionToken, _SchedulerState

    plan = _plan(
        {
            "workflow": {
                "nodes": [{"id": "a"}, {"id": "b"}, {"id": "j"}],
                "edges": [
                    {"id": "e0", "from": "a", "to": "b"},
                    {"id": "e1", "from": "a", "to": "j"},
                    {"id": "e2", "from": "b", "to": "j"},
                ],
                "entry_nodes": ["a"],
            }
        }
    )
    interp = WorkflowInterpreter(plan, _identity(), event_bus=None)
    state = _SchedulerState(plan)

    def tok(edge_id: str, produced_by: str, iteration: int) -> ExecutionToken:
        return ExecutionToken(
            edge_id=edge_id,
            branch_generation="g0",
            produced_by=produced_by,
            iteration=iteration,
        )

    # e2 arrives from iteration 9 while e1 sits half-open from iteration 1:
    # match keys differ -> NO activation despite full edge coverage.
    state.pending_tokens["j"] = [
        tok("e1", "a:attempt:1", 1),
        tok("e2", "b:attempt:9", 9),
    ]
    assert interp._try_join("j", None, state) == []
    assert len(state.pending_tokens["j"]) == 2  # nothing consumed on a mismatch

    # Same-key sibling completes the AND-join and is consumed.
    state.pending_tokens["j"][1] = tok("e2", "b:attempt:1", 1)
    activated = interp._try_join("j", None, state)
    assert len(activated) == 1
    joined = activated[0]
    assert joined.node_id == "j"
    assert joined.iteration == 1  # first visitation of j
    assert joined.generation == "g0"
    assert state.pending_tokens["j"] == []


@pytest.mark.asyncio
async def test_interpreter_owned_deadline_routes_timeout():
    """Per-node wall-clock deadline: the interpreter enforces it, tags the
    triage as TIMEOUT, marks record.timed_out, and the timeout edge routes."""
    scenario = {
        "workflow": {
            "nodes": [
                {"id": "slow", "timeout": 0.05},
                {"id": "handler"},
                {"id": "finalize"},
            ],
            "edges": [
                {"id": "e_to", "from": "slow", "to": "handler", "type": "timeout"},
                {"from": "handler", "to": "finalize"},
            ],
        },
        "failure_policy": "fail_fast",
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        await asyncio.sleep(0.3)  # far beyond the declared 0.05s deadline
        return {"task_id": node_ir.node_id, "status": "success"}

    results, outcome = await _run(plan, executor)

    # NODE_FAILED != WORKFLOW_FAILED: deadline breach routes to the handler.
    assert outcome.success
    slow = next(r for r in outcome.node_executions if r.scenario_node_id == "slow")
    assert slow.timed_out is True
    transition = outcome.transitions[0]
    assert transition.edge_type == EdgeType.TIMEOUT.value
    assert transition.transition_reason == "timeout_route"


@pytest.mark.asyncio
async def test_parallel_wave_runs_concurrently_wall_clock():
    """True parallel waves: two 0.25s branches in one wave finish well under
    the 0.5s sequential lower bound."""
    scenario = {
        "workflow": {
            "nodes": [{"id": "root"}, {"id": "l"}, {"id": "r"}],
            "edges": [
                {"from": "root", "to": "l", "type": "parallel"},
                {"from": "root", "to": "r", "type": "parallel"},
            ],
        },
        "failure_policy": "fail_fast",
    }
    plan = _plan(scenario)

    async def executor(node_ir, exec_id, parent):
        if node_ir.node_id == "root":
            return {"task_id": "root", "status": "success"}
        await asyncio.sleep(0.25)
        return {"task_id": node_ir.node_id, "status": "success"}

    start = time.perf_counter()
    results, outcome = await _run(plan, executor)
    elapsed = time.perf_counter() - start

    assert outcome.success
    assert sorted(r["task_id"] for r in results) == ["l", "r", "root"]
    assert elapsed < 0.45, f"wave did not overlap: took {elapsed:.3f}s"
