"""
tests/golden/test_golden_multi_attempt.py
Golden Verification Corpus: Multi-Attempt Result Representation Validation
"""

from eval_runner import reporter


def test_golden_multi_attempt_report_aggregation(capsys):
    scenario = {
        "id": "scen_multi_01",
        "title": "Multi-Attempt Test",
        "metadata": {"name": "Multi-Attempt Test", "industry": "fintech"},
    }

    # 3 attempts:
    # Attempt 1: task1 pass
    # Attempt 2: task1 fail
    # Attempt 3: task1 pass
    attempt_1 = [
        {
            "task_id": "t1",
            "status": "success",
            "metrics": [{"metric": "acc", "score": 1.0, "threshold": 0.8, "success": True}],
        }
    ]
    attempt_2 = [
        {
            "task_id": "t1",
            "status": "failure",
            "triage_tag": "TIMEOUT",
            "metrics": [{"metric": "acc", "score": 0.2, "threshold": 0.8, "success": False}],
        }
    ]
    attempt_3 = [
        {
            "task_id": "t1",
            "status": "success",
            "metrics": [{"metric": "acc", "score": 0.9, "threshold": 0.8, "success": True}],
        }
    ]

    multi_results = [attempt_1, attempt_2, attempt_3]

    reporter.generate_report(scenario, multi_results, export_trajectory=False, export_html=False)

    captured = capsys.readouterr().out

    # The summary must aggregate all attempts and not silently pick Attempt 1
    assert "Evaluation Mode: Multi-Attempt (N=3 attempts)" in captured
    assert "Attempt 1/3" in captured
    assert "Attempt 2/3" in captured
    assert "Attempt 3/3" in captured
    assert "Total Attempts (N): 3" in captured
    assert "Successful Attempts: 2" in captured
    assert "Failed Attempts: 1" in captured
    assert "Attempt Success Rate: 66.67%" in captured
