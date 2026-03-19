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
def test_identify_root_cause_policy():
    from eval_runner.triage import TriageEngine
    history = [
        {"role": "user", "content": "hello"},
        {"role": "agent", "content": {"action": "think"}},
        {"role": "environment", "content": {"status": "policy_violation"}}
    ]
    assert TriageEngine.identify_root_cause_index(history) == 2

def test_identify_root_cause_tool_error():
    from eval_runner.triage import TriageEngine
    history = [
        {"role": "agent", "content": {"action": "tool_x"}}, # Index 0
        {"role": "environment", "content": {"status": "error"}} # Index 1
    ]
    assert TriageEngine.identify_root_cause_index(history) == 0

def test_identify_root_cause_fallback():
    from eval_runner.triage import TriageEngine
    history = [
        {"role": "agent", "content": {"action": "bad_decision"}}, # Index 0
        {"role": "run_end", "status": "failed"} # Index 1
    ]
    assert TriageEngine.identify_root_cause_index(history) == 0

if __name__ == "__main__":
    test_triage_connection_error()
    test_triage_policy_violation()
    test_triage_tool_error()
    test_triage_success_no_tag()
    test_identify_root_cause_policy()
    test_identify_root_cause_tool_error()
    test_identify_root_cause_fallback()
    print("ALL TESTS PASSED MANUALLY")
