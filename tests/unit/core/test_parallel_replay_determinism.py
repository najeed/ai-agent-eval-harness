"""
tests/unit/core/test_parallel_replay_determinism.py

Deterministic Parallel Replay Regression Test (P0-2 remediation).
Asserts that parallel fan-out branches with overlapping and independent state mutations
merge deterministically by DAG compilation order rather than non-deterministic coroutine
wall-clock finish latency.
"""

import asyncio
import copy
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.runner import DefaultRunner


@pytest.mark.asyncio
async def test_parallel_branch_deterministic_state_merge_order():
    """
    Executes a parallel fan-out scenario twice with inverted tool execution delays.
    Branch A and Branch B both write to the state key 'shared_status' and independent keys.
    Asserts that the final merged state is strictly deterministic and identical across both runs.
    """
    scenario = {
        "aes_version": 1.4,
        "id": "parallel_merge_determinism",
        "description": "Tests deterministic post-gather merge order across sibling branches",
        "industry": "test",
        "metadata": {
            "name": "Parallel Merge Determinism",
            "id": "parallel_merge_determinism",
            "compliance_level": "Standard",
        },
        "tools": {
            "tool_alpha": {
                "state_changes": [
                    {"path": "shared_status", "value": "status_from_alpha", "op": "set"},
                    {"path": "alpha_branch_only", "value": "alpha_done", "op": "set"},
                ]
            },
            "tool_beta": {
                "state_changes": [
                    {"path": "shared_status", "value": "status_from_beta", "op": "set"},
                    {"path": "beta_branch_only", "value": "beta_done", "op": "set"},
                ]
            },
        },
        "workflow": {
            "nodes": [
                {
                    "id": "node_alpha",
                    "task_description": "Execute branch alpha task",
                    "required_tools": ["tool_alpha"],
                    "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}],
                    "expected_outcome": [
                        {
                            "target": "message",
                            "expected": "Done",
                            "mode": "contains",
                        }
                    ],
                },
                {
                    "id": "node_beta",
                    "task_description": "Execute branch beta task",
                    "required_tools": ["tool_beta"],
                    "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}],
                    "expected_outcome": [
                        {
                            "target": "message",
                            "expected": "Done",
                            "mode": "contains",
                        }
                    ],
                },
            ],
            "edges": [],
        },
        "evaluation": {"metrics": []},
    }

    # Run 1: Alpha has 50ms delay, Beta has 0ms delay (Beta coroutine finishes first)
    async def _agent_side_effect_run1(protocol, endpoint, message, history, turn_ctx):
        node_id = getattr(turn_ctx, "current_task_id", "") or ""
        if "node_alpha" in node_id or "alpha" in message.lower():
            await asyncio.sleep(0.05)
            if getattr(turn_ctx, "turn_number", 1) == 1:
                return {"action": "call_tool", "tool_name": "tool_alpha", "parameters": {}}
        else:
            if getattr(turn_ctx, "turn_number", 1) == 1:
                return {"action": "call_tool", "tool_name": "tool_beta", "parameters": {}}
        return {"action": "final_answer", "content": "Done"}

    runner1 = DefaultRunner()
    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        AsyncMock(side_effect=_agent_side_effect_run1),
    ):
        res1 = await runner1.run(copy.deepcopy(scenario), attempts=1, run_id="run_det_001")

    # Run 2: Beta has 50ms delay, Alpha has 0ms delay (Alpha coroutine finishes first)
    async def _agent_side_effect_run2(protocol, endpoint, message, history, turn_ctx):
        node_id = getattr(turn_ctx, "current_task_id", "") or ""
        if "node_beta" in node_id or "beta" in message.lower():
            await asyncio.sleep(0.05)
            if getattr(turn_ctx, "turn_number", 1) == 1:
                return {"action": "call_tool", "tool_name": "tool_beta", "parameters": {}}
        else:
            if getattr(turn_ctx, "turn_number", 1) == 1:
                return {"action": "call_tool", "tool_name": "tool_alpha", "parameters": {}}
        return {"action": "final_answer", "content": "Done"}

    runner2 = DefaultRunner()
    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        AsyncMock(side_effect=_agent_side_effect_run2),
    ):
        res2 = await runner2.run(copy.deepcopy(scenario), attempts=1, run_id="run_det_002")

    # Assert both runs succeeded
    assert res1.pass_at_k == 1.0
    # Retrieve terminal states and assert byte-for-byte state equality
    assert len(res1.attempts_results) == 1
    assert len(res2.attempts_results) == 1
    assert len(res1.attempts_results[0]) == 3
    assert len(res2.attempts_results[0]) == 3

    assert [n["task_id"] for n in res1.attempts_results[0]] == [
        "node_alpha",
        "node_beta",
        "workflow_verdict",
    ]
    assert [n["task_id"] for n in res2.attempts_results[0]] == [
        "node_alpha",
        "node_beta",
        "workflow_verdict",
    ]
