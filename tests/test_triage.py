import pytest
from eval_runner.triage import TriageEngine

def test_triage_connection_error():
    results = [
        {
            "task_id": "t1",
            "metrics": [{"success": False}],
            "conversation_history": [
                {"role": "system", "content": {"status": "error", "message": "Connection refused"}}
            ]
        }
    ]
    TriageEngine.apply_triage(results)
    assert results[0]["triage_tag"] == "CONNECTION_ERROR"

def test_triage_policy_violation():
    results = [
        {
            "task_id": "t1",
            "metrics": [{"success": False}],
            "conversation_history": [
                {"role": "environment", "content": {"status": "policy_violation"}}
            ]
        }
    ]
    TriageEngine.apply_triage(results)
    assert results[0]["triage_tag"] == "POLICY_VIOLATION"

def test_triage_tool_error():
    results = [
        {
            "task_id": "t1",
            "metrics": [{"success": False}],
            "conversation_history": [
                {"role": "environment", "content": {"status": "error"}}
            ]
        }
    ]
    TriageEngine.apply_triage(results)
    assert results[0]["triage_tag"] == "TOOL_ERROR"

def test_triage_success_no_tag():
    results = [
        {
            "task_id": "t1",
            "metrics": [{"success": True}],
            "conversation_history": []
        }
    ]
    TriageEngine.apply_triage(results)
    assert "triage_tag" not in results[0]
