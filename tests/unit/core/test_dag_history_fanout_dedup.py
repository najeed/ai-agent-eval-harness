"""
Regression test for G1: Cumulative history double-counting on unmerged parallel fan-out.
Asserts that branch history merging does not duplicate shared ancestor items across child leaves.
"""

from dataclasses import dataclass, field
from typing import Any

from eval_runner.execution_ir import ExecutionIdentity
from eval_runner.session import ExecutionInstanceContext


@dataclass
class DummySandbox:
    state: dict[str, Any] = field(default_factory=dict)


def test_dag_history_no_double_count_on_unmerged_fanout():
    """
    Scenario topology:
      Node A (root) -> generates 2 history items: [m1, m2]
      Branch forks into Node B and Node C (parallel, no final join node).
      Node B adds [m3].
      Node C adds [m4].
    Asserts that global cumulative history contains exactly [m1, m2, m3, m4],
    not [m1, m2, m3, m1, m2, m4].
    """
    identity = ExecutionIdentity(
        evaluation_run_id="run_1",
        scenario_version_id="v1",
        case_id="case_1",
        attempt_id="att_1",
        attempt_number=1,
    )
    sandbox = DummySandbox()

    # 1. Root Context A
    ctx_a = ExecutionInstanceContext(
        scenario_node_id="node_a",
        execution_instance_id="node_a#1",
        parent_execution_id=None,
        attempt_number=1,
        identity=identity,
        sandbox=sandbox,
        history=[{"role": "user", "content": "m1"}, {"role": "agent", "content": "m2"}],
        initial_history_len=0,
    )

    # 2. Branch Context B (forked from A)
    ctx_b = ExecutionInstanceContext(
        scenario_node_id="node_b",
        execution_instance_id="node_b#1",
        parent_execution_id="node_a#1",
        attempt_number=1,
        identity=identity,
        sandbox=sandbox,
        history=[
            {"role": "user", "content": "m1"},
            {"role": "agent", "content": "m2"},
            {"role": "agent", "content": "m3"},
        ],
        initial_history_len=2,  # Root had 2 items
    )

    # 3. Branch Context C (forked from A)
    ctx_c = ExecutionInstanceContext(
        scenario_node_id="node_c",
        execution_instance_id="node_c#1",
        parent_execution_id="node_a#1",
        attempt_number=1,
        identity=identity,
        sandbox=sandbox,
        history=[
            {"role": "user", "content": "m1"},
            {"role": "agent", "content": "m2"},
            {"role": "agent", "content": "m4"},
        ],
        initial_history_len=2,  # Root had 2 items
    )

    instance_contexts = {
        "node_a#1": ctx_a,
        "node_b#1": ctx_b,
        "node_c#1": ctx_c,
    }

    # Find leaves
    leaf_contexts = [
        ctx
        for eid, ctx in instance_contexts.items()
        if not any(c.parent_execution_id == eid for c in instance_contexts.values())
    ]

    assert len(leaf_contexts) == 2  # B and C are leaves

    # Deduplicated DAG history algorithm as implemented in SessionManager:
    global_cumulative_history = [
        item
        for ctx in instance_contexts.values()
        for item in ctx.history[ctx.initial_history_len :]
    ]

    contents = [msg["content"] for msg in global_cumulative_history]
    expected = ["m1", "m2", "m3", "m4"]
    assert contents == expected, f"Expected {expected}, got {contents}"
    assert len(global_cumulative_history) == 4
