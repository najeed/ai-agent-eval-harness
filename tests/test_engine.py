"""
Test suite for the multi-turn evaluation engine.

Tests the conversation loop in engine.py by mocking aiohttp responses
to simulate various agent behaviors: tool calls, multi-tool calls,
final answers, errors, timeouts, and max-turn limits.

Example:
    pytest tests/test_engine.py -v
"""

import pytest
import json
import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# engine.py uses relative imports, so we must import via the installed package
from eval_runner import engine
from eval_runner import metrics


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


class MockResponse:
    """Mock aiohttp response object."""

    def __init__(self, json_data, status=200, raise_for_status_error=None):
        self._json_data = json_data
        self.status = status
        self._raise_error = raise_for_status_error

    async def json(self):
        return self._json_data

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class MockSession:
    """Mock aiohttp.ClientSession with a queue of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_count = 0

    def post(self, url, **kwargs):
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        # Default: final_answer if more turns than expected
        return MockResponse({"action": "final_answer", "summary": "Done."})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# --- Tests ---

@pytest.mark.asyncio
async def test_engine_single_tool_call():
    """Agent calls one tool, sandbox responds, agent sends final_answer."""
    responses = [
        MockResponse({
            "action": "call_tool",
            "tool_name": "tool_a",
            "tool_params": {"id": "123"},
            "summary": "Called tool_a.",
        }),
        MockResponse({
            "action": "final_answer",
            "summary": "Task complete.",
        }),
    ]
    session = MockSession(responses)

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=session):
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    assert len(results) == 1
    task_result = results[0]
    assert task_result["task_id"] == "task-1"
    assert task_result["turns_taken"] >= 2
    # tool_a was used, tool_call_correctness should be 1.0
    metric = task_result["metrics"][0]
    assert metric["metric"] == "tool_call_correctness"
    assert metric["score"] == 1.0
    assert metric["success"] is True


@pytest.mark.asyncio
async def test_engine_multiple_tools():
    """Agent calls multiple tools in one turn."""
    responses = [
        MockResponse({
            "action": "call_multiple_tools",
            "tool_names": ["tool_a", "tool_b"],
            "summary": "Ran both tools.",
        }),
        MockResponse({
            "action": "final_answer",
            "summary": "All done.",
        }),
    ]
    session = MockSession(responses)
    scenario = _make_scenario(["tool_a", "tool_b"])

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=session):
        results = await engine.run_evaluation(scenario)

    metric = results[0]["metrics"][0]
    assert metric["score"] == 1.0


@pytest.mark.asyncio
async def test_engine_final_answer_first_turn():
    """Agent sends final_answer immediately without tool calls."""
    responses = [
        MockResponse({
            "action": "final_answer",
            "summary": "I already know the answer.",
        }),
    ]
    session = MockSession(responses)

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=session):
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    # No tools were used, so tool_call_correctness should be 0.0
    assert results[0]["metrics"][0]["score"] == 0.0
    assert results[0]["turns_taken"] == 1


@pytest.mark.asyncio
async def test_engine_max_turns_reached():
    """Agent keeps calling tools and never finishes — should stop at MAX_TURNS."""
    # Create responses that always call a tool
    responses = [
        MockResponse({
            "action": "call_tool",
            "tool_name": "tool_a",
            "tool_params": {},
            "summary": f"Turn {i}",
        })
        for i in range(engine.MAX_TURNS + 2)
    ]
    session = MockSession(responses)

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=session):
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    # Should have made MAX_TURNS calls (agent turn + environment turn each)
    assert results[0]["turns_taken"] > 0
    assert session._call_count <= engine.MAX_TURNS


@pytest.mark.asyncio
async def test_engine_connection_error():
    """Agent API is unreachable — should handle gracefully and return empty metrics."""
    import aiohttp as real_aiohttp

    class ErrorResponse:
        def __init__(self):
            pass
        async def __aenter__(self):
            raise real_aiohttp.ClientError("Connection refused")
        async def __aexit__(self, *args):
            pass

    class ErrorSession:
        def post(self, url, **kwargs):
            return ErrorResponse()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=ErrorSession()):
        results = await engine.run_evaluation(_make_scenario(["tool_a"]))

    # Should still return results, just with failed metrics
    assert len(results) == 1
    assert results[0]["metrics"][0]["score"] == 0.0


@pytest.mark.asyncio
async def test_engine_timeout():
    """Agent API times out — should handle gracefully."""

    class TimeoutResponse:
        async def __aenter__(self):
            raise asyncio.TimeoutError()
        async def __aexit__(self, *args):
            pass

    class TimeoutSession:
        def post(self, url, **kwargs):
            return TimeoutResponse()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=TimeoutSession()):
        results = await engine.run_evaluation(_make_scenario())

    assert len(results) == 1
    assert results[0]["metrics"][0]["success"] is False


@pytest.mark.asyncio
async def test_engine_generic_accuracy_metric():
    """Verify generic accuracy metric is dispatched for non-tool metrics."""
    scenario = {
        "scenario_id": "accuracy-test",
        "title": "Accuracy Test",
        "description": "Test generic accuracy.",
        "use_case": "Testing",
        "core_function": "Unit Test",
        "industry": "test",
        "tasks": [
            {
                "task_id": "task-1",
                "description": "Retrieve info.",
                "expected_outcome": "Info retrieved.",
                "required_tools": [],
                "success_criteria": [
                    {"metric": "information_retrieval_accuracy", "threshold": 0.8}
                ],
            }
        ],
    }
    responses = [
        MockResponse({
            "action": "final_answer",
            "summary": "The customer is on the 100 Mbps plan.",
        }),
    ]
    session = MockSession(responses)

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=session):
        results = await engine.run_evaluation(scenario)

    metric = results[0]["metrics"][0]
    assert metric["metric"] == "information_retrieval_accuracy"
    assert metric["score"] == 1.0  # non-empty summary → 1.0


@pytest.mark.asyncio
async def test_engine_communication_clarity_metric():
    """Verify communication_clarity metric is dispatched correctly."""
    scenario = {
        "scenario_id": "clarity-test",
        "title": "Clarity Test",
        "description": "Test communication clarity.",
        "use_case": "Testing",
        "core_function": "Unit Test",
        "industry": "test",
        "tasks": [
            {
                "task_id": "task-1",
                "description": "Explain the issue.",
                "expected_outcome": "Clear explanation.",
                "required_tools": [],
                "success_criteria": [
                    {"metric": "communication_clarity", "threshold": 1.0}
                ],
            }
        ],
    }
    responses = [
        MockResponse({
            "action": "final_answer",
            "summary": "The issue is with the customer's local Wi-Fi network.",
        }),
    ]
    session = MockSession(responses)

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=session):
        results = await engine.run_evaluation(scenario)

    metric = results[0]["metrics"][0]
    assert metric["metric"] == "communication_clarity"
    assert metric["score"] == 1.0


@pytest.mark.asyncio
async def test_engine_provide_instructions_action():
    """Agent signals provide_instructions — should end conversation."""
    responses = [
        MockResponse({
            "action": "provide_instructions",
            "instructions": "Please restart your router.",
            "summary": "Provided instructions.",
        }),
    ]
    session = MockSession(responses)

    with patch("eval_runner.engine.aiohttp.ClientSession", return_value=session):
        results = await engine.run_evaluation(_make_scenario())

    assert results[0]["turns_taken"] == 1
    assert session._call_count == 1
