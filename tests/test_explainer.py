import json
import pytest
from pathlib import Path
from eval_runner.explainer import explain_trace

@pytest.fixture
def mock_trace(tmp_path):
    def _create_trace(events):
        trace_file = tmp_path / "run.jsonl"
        with open(trace_file, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return trace_file
    return _create_trace

def test_explain_infinite_loop(mock_trace):
    events = [
        {"event": "prompt", "content": "What is the capital of France?"} for _ in range(12)
    ]
    trace_path = mock_trace(events)
    diagnosis = explain_trace(trace_path)
    assert "Infinite Loop" in diagnosis["root_cause"]
    assert "circular reasoning" in diagnosis["suggestion"].lower()

def test_explain_tool_timeout(mock_trace):
    events = [
        {"event": "tool_call", "tool": "search"},
        {"event": "tool_result", "tool": "search", "result": "Error: request timeout after 30s"}
    ]
    trace_path = mock_trace(events)
    diagnosis = explain_trace(trace_path)
    assert "Tool Timeout" in diagnosis["root_cause"]
    assert "search" in diagnosis["root_cause"]
    assert "increase the tool sandbox timeout" in diagnosis["suggestion"].lower()

def test_explain_tool_error(mock_trace):
    events = [
        {"event": "tool_call", "tool": "executor"},
        {"event": "tool_result", "tool": "executor", "result": "Exception: DivisionByZero"}
    ]
    trace_path = mock_trace(events)
    diagnosis = explain_trace(trace_path)
    assert "Tool Error in executor" in diagnosis["root_cause"]
    assert "DivisionByZero" in diagnosis["root_cause"]

def test_explain_policy_violation(mock_trace):
    events = [
        {"event": "evaluation", "metric": "policy_compliance", "value": 0.0}
    ]
    trace_path = mock_trace(events)
    diagnosis = explain_trace(trace_path)
    assert "Policy Violation" in diagnosis["root_cause"]
    assert "PII" in diagnosis["suggestion"]

def test_explain_task_not_completed(mock_trace):
    events = [
        {"event": "run_end", "status": "failure"}
    ]
    trace_path = mock_trace(events)
    diagnosis = explain_trace(trace_path)
    assert "Target Task Not Completed" in diagnosis["root_cause"]

def test_explain_invalid_path():
    diagnosis = explain_trace(Path("non_existent.jsonl"))
    assert "Error reading trace" in diagnosis["root_cause"]
