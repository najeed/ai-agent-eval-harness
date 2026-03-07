"""
Test suite for the evaluation report generator.

Tests reporter.generate_report() output formatting, success/failure
status display, and edge cases like empty results.

Example:
    pytest tests/test_reporter.py -v
"""

import pytest
import sys
from io import StringIO
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

import reporter


def _capture_report(scenario, results):
    """Run generate_report and capture stdout."""
    from contextlib import redirect_stdout
    buf = StringIO()
    with redirect_stdout(buf):
        reporter.generate_report(scenario, results)
    return buf.getvalue()


SAMPLE_SCENARIO = {
    "scenario_id": "test-001",
    "title": "Test Report Scenario",
    "industry": "test",
    "description": "A test scenario for report generation.",
}


def test_report_all_tasks_pass():
    """All metrics pass → report shows SUCCESS and 100% rate."""
    results = [
        {
            "task_id": "task-1",
            "metrics": [
                {"metric": "tool_call_correctness", "score": 1.0, "threshold": 1.0, "success": True},
                {"metric": "communication_clarity", "score": 1.0, "threshold": 1.0, "success": True},
            ],
        },
    ]
    output = _capture_report(SAMPLE_SCENARIO, results)
    assert "SUCCESS" in output
    assert "100.00%" in output
    assert "FAILURE" not in output


def test_report_task_fails():
    """One metric fails → report shows FAILURE and <100% rate."""
    results = [
        {
            "task_id": "task-1",
            "metrics": [
                {"metric": "tool_call_correctness", "score": 0.0, "threshold": 1.0, "success": False},
            ],
        },
    ]
    output = _capture_report(SAMPLE_SCENARIO, results)
    assert "FAILURE" in output
    assert "0.00%" in output


def test_report_mixed_tasks():
    """Multiple tasks with mixed results → correct success rate."""
    results = [
        {
            "task_id": "task-1",
            "metrics": [
                {"metric": "tool_call_correctness", "score": 1.0, "threshold": 1.0, "success": True},
            ],
        },
        {
            "task_id": "task-2",
            "metrics": [
                {"metric": "tool_call_correctness", "score": 0.0, "threshold": 1.0, "success": False},
            ],
        },
    ]
    output = _capture_report(SAMPLE_SCENARIO, results)
    assert "50.00%" in output
    assert "Total Tasks: 2" in output
    assert "Successful Tasks: 1" in output
    assert "Failed Tasks: 1" in output


def test_report_displays_scenario_info():
    """Report header contains scenario title, ID, industry, description."""
    results = [
        {
            "task_id": "task-1",
            "metrics": [
                {"metric": "accuracy", "score": 0.9, "threshold": 0.8, "success": True},
            ],
        },
    ]
    output = _capture_report(SAMPLE_SCENARIO, results)
    assert "Test Report Scenario" in output
    assert "test-001" in output
    assert "test" in output


def test_report_metric_display_format():
    """Each metric line shows name, score, threshold."""
    results = [
        {
            "task_id": "task-1",
            "metrics": [
                {"metric": "information_retrieval_accuracy", "score": 0.85, "threshold": 0.8, "success": True},
            ],
        },
    ]
    output = _capture_report(SAMPLE_SCENARIO, results)
    assert "information_retrieval_accuracy" in output
    assert "0.85" in output
    assert "0.80" in output
