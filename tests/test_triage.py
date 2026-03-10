import pytest

def test_triage_connection_error():
    from eval_runner.triage import TriageEngine
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
    assert results[0].get("triage_tag") == "CONNECTION_ERROR"

def test_triage_policy_violation():
    from eval_runner.triage import TriageEngine
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
    assert results[0].get("triage_tag") == "POLICY_VIOLATION"

def test_triage_tool_error():
    from eval_runner.triage import TriageEngine
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
    assert results[0].get("triage_tag") == "TOOL_ERROR"

def test_triage_success_no_tag():
    from eval_runner.triage import TriageEngine
    results = [
        {
            "task_id": "t1",
            "metrics": [{"success": True}],
            "conversation_history": []
        }
    ]
    TriageEngine.apply_triage(results)
if __name__ == "__main__":
    test_triage_connection_error()
    test_triage_policy_violation()
    test_triage_tool_error()
    test_triage_success_no_tag()
    print("ALL TESTS PASSED MANUALLY")
