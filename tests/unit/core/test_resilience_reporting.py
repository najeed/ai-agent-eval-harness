from eval_runner.reporter import generate_html_report, generate_report
from eval_runner.triage import TriageEngine


def test_reporter_success_check_empty_metrics():
    """Verify that reporter correctly identifies failures when metrics are empty."""
    # Scenario: A task failed (e.g. timeout or crash) and returned empty metrics
    results = [
        {
            "task_id": "failed_task",
            "status": "failure",
            "metrics": [],
            "triage_tag": "FATAL_ENGINE_ERROR",
        }
    ]

    # We'll mock the print function to capture the output of generate_report
    import io
    from contextlib import redirect_stdout

    scenario = {"id": "test", "title": "Test Scenario"}
    f = io.StringIO()
    with redirect_stdout(f):
        generate_report(scenario, results, export_trajectory=False, export_html=False)

    output = f.getvalue()
    assert "Task: failed_task [FAILURE [FATAL_ENGINE_ERROR]]" in output
    assert "Successful Tasks: 0" in output
    assert "Failed Tasks: 1" in output
    assert "Overall Success Rate: 0.00%" in output


def test_html_reporter_success_check_empty_metrics():
    """Verify that HTML reporter correctly identifies failures when metrics are empty."""
    results = [
        {
            "task_id": "failed_task",
            "status": "failure",
            "metrics": [],
            "triage_tag": "FATAL_ENGINE_ERROR",
        }
    ]
    scenario = {"id": "test", "title": "Test Scenario"}

    # generate_html_report returns a Path
    # We'll just verify the logic by checking if standalone_...html was created
    # and if the internal successful_tasks count (which we can't directly check without mocking)
    # is handled. Actually, let's just test the logic directly if possible.

    # We can test the helper logic inside generate_html_report if it was extracted,
    # but it's embedded. So we'll check the generated file content.

    report_path = generate_html_report(scenario, results, standalone=True)
    try:
        with open(report_path, encoding="utf-8") as f:
            content = f.read()
            # The HTML report should show 0.0% success rate
            assert "0.0%" in content
            assert "0 / 1" in content
            assert "FAILED [FATAL_ENGINE_ERROR]" in content
    finally:
        if report_path.exists():
            report_path.unlink()


def test_triage_engine_respects_existing_tag():
    """Verify that TriageEngine respects an existing triage_tag (e.g. from session crash)."""
    results = [
        {
            "task_id": "crashed_task",
            "status": "failure",
            "metrics": [],
            "triage_tag": "FATAL_ENGINE_ERROR",
            "conversation_history": [],
        }
    ]

    # apply_triage should NOT overwrite FATAL_ENGINE_ERROR
    TriageEngine.apply_triage(results)
    assert results[0]["triage_tag"] == "FATAL_ENGINE_ERROR"


def test_session_recovery_result_structure():
    """Verify that the failure result from session.py has all required keys for reporter."""
    # This is a bit of a contract test.
    # We want to ensure that the dictionary returned by the session's except block
    # contains all keys that reporter.py expects.

    # From session.py (user's edit):
    # {
    #     "task_id": node_id if "node_id" in locals() else "unknown",
    #     "status": "failure",
    #     "triage_tag": "FATAL_ENGINE_ERROR",
    #     "message": err_msg,
    #     "metrics": [],
    #     "turns_taken": 0,
    #     "used_tools": [],
    #     "conversation_history": history if "history" in locals() else [],
    #     "traceback": tb
    # }

    # We mock a result list and pass it to generate_report to ensure no KeyErrors
    fake_crash_result = [
        {
            "task_id": "crashed_node",
            "status": "failure",
            "triage_tag": "FATAL_ENGINE_ERROR",
            "message": "Simulated crash",
            "metrics": [],
            "turns_taken": 0,
            "used_tools": [],
            "conversation_history": [],
            "traceback": "...",
        }
    ]

    import io
    from contextlib import redirect_stdout

    scenario = {"id": "test", "title": "Test Scenario"}
    f = io.StringIO()
    with redirect_stdout(f):
        # This should not raise KeyError or crash
        generate_report(scenario, fake_crash_result, export_trajectory=False, export_html=False)

    output = f.getvalue()
    assert "FATAL_ENGINE_ERROR" in output


def test_resilience_reporting_attempt_success_triage_paradox():
    """Verify that runner._is_attempt_successful rejects attempts with failure status
    even if metrics passed.
    """
    from eval_runner.runner import DefaultRunner

    runner = DefaultRunner()

    # Scenario 1: metrics success but status failure
    attempt_res = [{"task_id": "failed_task", "status": "failure", "metrics": [{"success": True}]}]
    assert runner._is_attempt_successful(attempt_res) is False


if __name__ == "__main__":
    # For manual execution
    test_reporter_success_check_empty_metrics()
    test_html_reporter_success_check_empty_metrics()
    test_triage_engine_respects_existing_tag()
    test_session_recovery_result_structure()
    test_resilience_reporting_attempt_success_triage_paradox()
    print("RESILIENCE TESTS PASSED")
