import pytest
import json
from pathlib import Path
from eval_runner import reporter, config


@pytest.fixture
def mock_results():
    return [
        {
            "task_id": "t1",
            "metrics": [{"metric": "m1", "score": 1, "threshold": 0.5, "success": True}],
            "conversation_history": [
                {"role": "agent", "content": {"action": "think"}, "agent_name": "TestBot"},
                {"role": "environment", "content": {"status": "success"}},
                {"role": "agent", "content": {"action": "final_answer"}},
            ],
        }
    ]


def test_save_trajectory(tmp_path, mock_results):
    """Test that trajectories are saved correctly to JSON."""
    scenario = {"scenario_id": "s1", "title": "Test Scen"}
    reporter.save_trajectory(scenario, mock_results, base_dir=tmp_path)

    # Check if file exists
    traj_dir = tmp_path / "reports" / "trajectories"
    assert traj_dir.exists()
    files = list(traj_dir.glob("s1_*.json"))
    assert len(files) == 1

    with open(files[0], "r") as f:
        data = json.load(f)
        assert data["metadata"]["scenario_id"] == "s1"
        assert len(data["results"]) == 1


def test_generate_mermaid_trajectory(mock_results):
    """Test Mermaid graph generation."""
    mermaid = reporter.generate_mermaid_trajectory(mock_results[0])
    assert "graph TD" in mermaid
    assert "Turn_1_agent" in mermaid
    assert "TestBot" in mermaid
    assert "final_answer" in mermaid


def test_generate_mermaid_violation():
    """Test Mermaid styling for policy violations."""
    res = {
        "conversation_history": [
            {"role": "agent", "content": {"action": "bad_action"}},
            {"role": "environment", "content": {"status": "policy_violation"}},
        ]
    }
    mermaid = reporter.generate_mermaid_trajectory(res)
    assert "((Violation))" in mermaid
    assert "fill:#f96" in mermaid


def test_generate_html_report(tmp_path, mock_results):
    """Test HTML report generation."""
    scenario = {"scenario_id": "h1", "title": "HTML Test", "industry": "legal"}

    # Override report dir for testing
    old_dir = config.HTML_REPORTS_DIR
    config.HTML_REPORTS_DIR = tmp_path / "html"

    try:
        path = reporter.generate_html_report(scenario, mock_results)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "HTML Test" in content
        assert "PASSED" in content
        assert "mermaid" in content
    finally:
        config.HTML_REPORTS_DIR = old_dir


def test_generate_report_console_output(capsys, mock_results):
    """Test the main generate_report function for console output."""
    scenario = {"scenario_id": "c1", "title": "Console Test"}
    reporter.generate_report(scenario, mock_results, export_trajectory=False, export_html=False)

    captured = capsys.readouterr()
    assert "EVALUATION REPORT" in captured.out
    assert "Console Test" in captured.out
    assert "Overall Success Rate: 100.00%" in captured.out
