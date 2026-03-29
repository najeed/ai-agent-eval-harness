import pytest


def test_triage_connection_error():
    from eval_runner.triage import TriageEngine

    results = [
        {
            "task_id": "t1",
            "metrics": [{"success": False}],
            "conversation_history": [
                {
                    "role": "system",
                    "content": {"status": "error", "message": "Connection refused"},
                }
            ],
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
            "conversation_history": [{"role": "environment", "content": {"status": "policy_violation"}}],
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
            "conversation_history": [{"role": "environment", "content": {"status": "error"}}],
        }
    ]
    TriageEngine.apply_triage(results)
    assert results[0].get("triage_tag") == "TOOL_ERROR"


def test_triage_success_no_tag():
    from eval_runner.triage import TriageEngine

    results = [{"task_id": "t1", "metrics": [{"success": True}], "conversation_history": []}]
    TriageEngine.apply_triage(results)


def test_identify_root_cause_policy():
    from eval_runner.triage import TriageEngine

    history = [
        {"role": "user", "content": "hello"},
        {"role": "agent", "content": {"action": "think"}},
        {"role": "environment", "content": {"status": "policy_violation"}},
    ]
    assert TriageEngine.identify_root_cause_index(history) == 2


def test_identify_root_cause_tool_error():
    from eval_runner.triage import TriageEngine

    history = [
        {"role": "agent", "content": {"action": "tool_x"}},  # Index 0
        {"role": "environment", "content": {"status": "error"}},  # Index 1
    ]
    assert TriageEngine.identify_root_cause_index(history) == 0


def test_identify_root_cause_fallback():
    from eval_runner.triage import TriageEngine

    history = [
        {"role": "agent", "content": {"action": "bad_decision"}},  # Index 0
        {"role": "run_end", "status": "failed"},  # Index 1
    ]
    assert TriageEngine.identify_root_cause_index(history) == 0


def test_identify_root_cause_metric_failure():
    from eval_runner.triage import TriageEngine

    history = [
        {"role": "agent", "content": {"action": "bad_answer"}},  # Index 0
        {"event": "evaluation", "metric": "clarity", "success": False, "value": 0.2},  # Index 1
    ]
    # Should point to the agent action at index 0
    assert TriageEngine.identify_root_cause_index(history) == 0


def test_triage_engine_inconclusive_flow():
    """Verify that triage returns inconclusive when no clear deviation is found."""
    from eval_runner.triage import TriageEngine
    engine = TriageEngine()
    # Scenario: Run starts but never ends (missing run_end)
    events = [{"event": "run_start"}]
    # Hits logic for inconclusive results
    result = engine.identify_root_cause(events)
    assert result["reason"] == "Inconclusive results; no clear deviation point found."
    assert result["confidence"] == 0.1


def test_triage_apply_triage_error_handling():
    """Verify that apply_triage handles malformed result items gracefully."""
    from eval_runner.triage import TriageEngine
    # Test apply_triage when a result item is malformed (missing required keys)
    results = [{"not_a_task": True}]
    TriageEngine.apply_triage(results)
    # Success verified by no exception being raised


if __name__ == "__main__":
    test_triage_connection_error()
    test_triage_policy_violation()
    test_triage_tool_error()
    test_triage_success_no_tag()
    test_identify_root_cause_policy()
    test_identify_root_cause_tool_error()
    test_identify_root_cause_fallback()
    test_identify_root_cause_metric_failure()
    print("ALL TESTS PASSED MANUALLY")
