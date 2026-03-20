"""
test_engine.py

Test suite for the multi-turn evaluation engine.
Updated for modular AgentAdapterRegistry, AsyncMock, and dynamic metrics.
"""

import pytest
import json
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from eval_runner import engine
from eval_runner import metrics


@pytest.fixture(autouse=True)
def reset_global_state():
    from eval_runner.events import EventEmitter
    from eval_runner.plugins import manager

    EventEmitter.listeners = {}
    manager.plugins = []
    yield


@pytest.mark.asyncio
async def test_pass_at_k_protocol():
    """Verify that engine runs k attempts and calculates pass@k. (Migrated from test_phase3.py)"""
    scenario = {
        "scenario_id": "test-k",
        "tasks": [
            {
                "task_id": "task-1",
                "description": "Do something",
                "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
            }
        ],
    }

    # Mock agent to succeed in 1 out of 2 attempts
    attempt_count = 0

    async def mock_agent_call(payload, protocol="http", endpoint=None):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            return {"action": "final_answer", "summary": "Success"}
        else:
            return {
                "action": "final_answer",
                "summary": "",
            }  # Fails generic_accuracy (length > 0)

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.side_effect = mock_agent_call
        results = await engine.run_evaluation(scenario, attempts=2)

        assert len(results) == 2

        successes = 0
        for attempt in results:
            if all(
                all(
                    m["success"]
                    for m in tr["metrics"]
                    if m["metric"] != "consistency_score"
                )
                for tr in attempt
            ):
                successes += 1

        assert successes == 1


@pytest.mark.asyncio
async def test_consistency_score_integration():
    """Verify that consistency score is calculated across attempts. (Migrated from test_phase3.py)"""
    scenario = {
        "scenario_id": "test-consistency",
        "tasks": [
            {"task_id": "task-1", "description": "Do something", "success_criteria": []}
        ],
    }

    # Mock agent to give same answer twice
    async def mock_agent_call(payload, protocol="http", endpoint=None):
        return {"action": "final_answer", "summary": "Identical result"}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        side_effect=mock_agent_call,
    ):
        results = await engine.run_evaluation(scenario, attempts=2)

        # Check task metrics in the last attempt
        task_res = results[-1][0]
        consistency_metric = next(
            (m for m in task_res["metrics"] if m["metric"] == "consistency_score"), None
        )

        assert consistency_metric is not None
        assert consistency_metric["score"] == 1.0


# --- Helpers ---


def _make_scenario(required_tools=None):
    """Create a minimal scenario for testing."""
    return {
        "scenario_id": "test-scenario",
        "title": "Test Scenario",
        "description": "For engine tests.",
        "use_case": "Testing",
        "core_function": "Unit Test",
        "industry": "test",
        "tasks": [
            {
                "task_id": "task-1",
                "description": "Do the thing.",
                "expected_outcome": "Thing is done.",
                "required_tools": required_tools or ["tool_a"],
                "success_criteria": [
                    {"metric": "tool_call_correctness", "threshold": 1.0}
                ],
            }
        ],
    }


# --- Tests ---


@pytest.mark.asyncio
async def test_engine_single_tool_call():
    """Agent calls one tool, sandbox responds, agent sends final_answer."""
    responses = [
        {
            "action": "call_tool",
            "tool_name": "tool_a",
            "tool_params": {"id": "123"},
            "summary": "Called tool_a.",
        },
        {
            "action": "final_answer",
            "summary": "Task complete.",
        },
    ]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    assert len(results) == 1
    task_result = results[0]
    assert task_result["task_id"] == "task-1"
    assert len(task_result["conversation_history"]) >= 2

    # Find tool_call_correctness metric
    metric = next(
        m for m in task_result["metrics"] if m["metric"] == "tool_call_correctness"
    )
    assert metric["score"] == 1.0
    assert metric["success"] is True


@pytest.mark.asyncio
async def test_engine_multiple_tools():
    """Agent calls multiple tools in one turn."""
    responses = [
        {
            "action": "call_multiple_tools",
            "tool_names": ["tool_a", "tool_b"],
            "summary": "Ran both tools.",
        },
        {
            "action": "final_answer",
            "summary": "All done.",
        },
    ]
    scenario = _make_scenario(["tool_a", "tool_b"])

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(scenario)

    metric = next(
        m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness"
    )
    assert metric["score"] == 1.0


@pytest.mark.asyncio
async def test_engine_final_answer_first_turn():
    """Agent sends final_answer immediately without tool calls."""
    responses = [
        {
            "action": "final_answer",
            "summary": "I already know the answer.",
        },
    ]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    # No tools were used, so tool_call_correctness should be 0.0
    metric = next(
        m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness"
    )
    assert metric["score"] == 0.0
    assert results[0]["turns_taken"] == 1


@pytest.mark.asyncio
async def test_engine_max_turns_reached(monkeypatch):
    """Agent keeps calling tools and never finishes — should stop at MAX_TURNS."""
    monkeypatch.setattr("eval_runner.engine.MAX_TURNS", 2)

    responses = [
        {
            "action": "call_tool",
            "tool_name": "tool_a",
            "tool_params": {},
            "summary": f"Turn {i}",
        }
        for i in range(5)
    ]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    # It should stop at MAX_TURNS (which is 2)
    # The loop for turn in range(1, MAX_TURNS + 1) runs for 1, 2.
    assert results[0]["turns_taken"] <= 3


@pytest.mark.asyncio
async def test_engine_connection_error():
    """Agent API is unreachable — should handle gracefully and return empty metrics."""
    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        side_effect=Exception("Connection Error"),
    ):
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    assert len(results) == 1
    metric = next(
        m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness"
    )
    assert metric["score"] == 0.0


@pytest.mark.asyncio
async def test_engine_timeout():
    """Agent API times out — should handle gracefully."""
    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        side_effect=asyncio.TimeoutError(),
    ):
        results = await engine.run_evaluation(_make_scenario())

    assert len(results) == 1
    metric = next(
        m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness"
    )
    assert metric["success"] is False


@pytest.mark.asyncio
async def test_engine_generic_accuracy_metric():
    """Verify generic accuracy metric is dispatched for non-tool metrics."""
    scenario = {
        "scenario_id": "accuracy-test",
        "tasks": [
            {
                "task_id": "task-1",
                "description": "Retrieve info.",
                "required_tools": [],
                "success_criteria": [
                    {"metric": "information_retrieval_accuracy", "threshold": 0.8}
                ],
            }
        ],
    }
    responses = [
        {
            "action": "final_answer",
            "summary": "The customer is on the 100 Mbps plan.",
        },
    ]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(scenario)

    metric = next(
        m
        for m in results[0]["metrics"]
        if m["metric"] == "information_retrieval_accuracy"
    )
    assert metric["score"] == 1.0


@pytest.mark.asyncio
async def test_engine_communication_clarity_metric():
    """Verify communication_clarity metric is dispatched correctly."""
    scenario = {
        "scenario_id": "clarity-test",
        "tasks": [
            {
                "task_id": "task-1",
                "description": "Explain the issue.",
                "required_tools": [],
                "success_criteria": [
                    {"metric": "communication_clarity", "threshold": 1.0}
                ],
            }
        ],
    }
    responses = [
        {
            "action": "final_answer",
            "summary": "The issue is with the customer's local Wi-Fi network.",
        },
    ]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(scenario)

    metric = next(
        m for m in results[0]["metrics"] if m["metric"] == "communication_clarity"
    )
    assert metric["score"] == 1.0


@pytest.mark.asyncio
async def test_engine_policy_violation_feedback_loop():
    """Verify that a policy violation is sent back to the agent as feedback."""
    scenario = {
        "scenario_id": "policy-test",
        "industry": "test",
        "policies": {"apply_refund": {"max_limit": 50}},
        "tasks": [
            {
                "task_id": "task-1",
                "required_tools": ["apply_refund"],
                "success_criteria": [{"metric": "policy_compliance", "threshold": 1.0}],
            }
        ],
    }
    responses = [
        {
            "action": "call_tool",
            "tool_name": "apply_refund",
            "tool_params": {"amount": 100},
            "summary": "Trying refund.",
        },
        {"action": "final_answer", "summary": "Limited the refund to 50."},
    ]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(scenario)

    task_result = results[0]
    compliance = next(
        m for m in task_result["metrics"] if m["metric"] == "policy_compliance"
    )
    assert compliance["score"] == 0.0
    assert compliance["success"] is False


@pytest.mark.asyncio
async def test_engine_state_verification_metric():
    """Verify that state_verification metric is calculated and reported."""
    scenario = {
        "scenario_id": "state-test",
        "industry": "test",
        "initial_state": {"current_plan": "Basic"},
        "tools": {
            "update_plan": {
                "state_changes": [{"path": "current_plan", "value": "Premium"}],
                "output": {"status": "success"},
            }
        },
        "tasks": [
            {
                "task_id": "task-1",
                "required_tools": ["update_plan"],
                "expected_state_changes": [
                    {"path": "current_plan", "value": "Premium"}
                ],
                "success_criteria": [
                    {"metric": "state_verification", "threshold": 1.0}
                ],
            }
        ],
    }
    responses = [
        {
            "action": "call_tool",
            "tool_name": "update_plan",
            "tool_params": {"current_plan": "Premium"},
            "summary": "Updating plan.",
        },
        {"action": "final_answer", "summary": "Plan updated."},
    ]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_call:
        mock_call.side_effect = responses
        results = await engine.run_evaluation(scenario)

    task_result = results[0]
    state_metric = next(
        m for m in task_result["metrics"] if m["metric"] == "state_verification"
    )
    assert state_metric["score"] == 1.0
    assert state_metric["success"] is True
