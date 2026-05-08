import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from eval_runner import config, reporter


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
    scenario = {"id": "s1", "title": "Test Scen"}
    reporter.save_trajectory(scenario, mock_results, base_dir=tmp_path)

    # Check if file exists
    traj_dir = tmp_path / "reports" / "trajectories"
    assert traj_dir.exists()
    files = list(traj_dir.glob("s1_*.json"))
    assert len(files) == 1

    with open(files[0]) as f:
        data = json.load(f)
        assert data["metadata"]["id"] == "s1"
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
    scenario = {"id": "h1", "title": "HTML Test", "industry": "legal"}

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
    scenario = {"id": "c1", "title": "Console Test"}
    reporter.generate_report(scenario, mock_results, export_trajectory=False, export_html=False)

    captured = capsys.readouterr()
    assert "EVALUATION REPORT" in captured.out
    assert "Console Test" in captured.out
    assert "Overall Success Rate: 100.00%" in captured.out


def test_generate_mermaid_complex():
    # unknown action with framework/protocol
    res = {
        "conversation_history": [
            {
                "role": "agent",
                "content": {"action": "unknown", "metadata": {"framework": "LangChain"}},
            },
            {"role": "agent", "content": {"action": "unknown"}, "protocol": "http"},
        ]
    }
    mermaid = reporter.generate_mermaid_trajectory(res)
    assert "LangChain" in mermaid
    assert "http" in mermaid

    # Agent string truncation
    res2 = {
        "conversation_history": [
            {
                "role": "agent",
                "content": {"action": "think"},
                "agent": "http://verylongagentnameherethatshouldbetruncated.com",
            },
        ]
    }
    mermaid2 = reporter.generate_mermaid_trajectory(res2)
    assert "..." in mermaid2


def test_generate_html_report_advanced(tmp_path, mock_results):
    scenario = {"id": "h2", "title": "Advanced HTML"}

    # is_verified = True
    trace_path = tmp_path / "run.json"
    trace_path.write_text("{}")
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text("{}")

    metadata = {"trace_path": str(trace_path), "protocol": "socket"}
    # Clear agent_name to force protocol fallback in HTML
    for r in mock_results:
        r.pop("agent_name", None)
        if "conversation_history" in r:
            for turn in r["conversation_history"]:
                turn.pop("agent_name", None)

    old_dir = config.HTML_REPORTS_DIR
    config.HTML_REPORTS_DIR = tmp_path / "html"

    try:
        with patch.dict(os.environ, {"AGENT_SOCKET_ADDR": "socket-connection"}):
            path = reporter.generate_html_report(scenario, mock_results, metadata=metadata)
            content = path.read_text(encoding="utf-8")
            assert "Evaluation Report" in content

        # Discovery from results
        for r in mock_results:
            if "conversation_history" in r:
                for t in r["conversation_history"]:
                    if t.get("role") == "agent":
                        t["agent_name"] = "DiscoveredBot"

        path2 = reporter.generate_html_report(scenario, mock_results, metadata={})
        content2 = path2.read_text(encoding="utf-8")
        assert "DiscoveredBot" in content2

        # protocol fallback in HTML
        path_http = reporter.generate_html_report(
            scenario, mock_results, metadata={"protocol": "http"}
        )
        assert "http" in path_http.read_text(encoding="utf-8").lower()

        with patch.dict(os.environ, {"AGENT_LOCAL_CMD": "local-subprocess"}):
            path_local = reporter.generate_html_report(
                scenario, mock_results, metadata={"protocol": "local"}
            )
            assert "local" in path_local.read_text(encoding="utf-8").lower()
    finally:
        config.HTML_REPORTS_DIR = old_dir


def test_generate_report_advanced(capsys, mock_results):
    scenario = {"id": "a1", "title": "Advanced Report"}

    # Clear agent_name
    for r in mock_results:
        r.pop("agent_name", None)
        if "conversation_history" in r:
            for turn in r["conversation_history"]:
                turn.pop("agent_name", None)

    with patch.dict(
        os.environ,
        {"AGENT_LOCAL_CMD": "local-subprocess", "AGENT_SOCKET_ADDR": "socket-connection"},
    ):
        metadata = {"protocol": "local"}
        reporter.generate_report(scenario, mock_results, metadata=metadata, export_html=False)
        captured = capsys.readouterr()
        assert "EVALUATION REPORT" in captured.out

        metadata_socket = {"protocol": "socket"}
        reporter.generate_report(
            scenario, mock_results, metadata=metadata_socket, export_html=False
        )
        captured = capsys.readouterr()
        assert "EVALUATION REPORT" in captured.out

    # Discovery from results
    if "conversation_history" in mock_results[0]:
        for turn in mock_results[0]["conversation_history"]:
            if turn.get("role") == "agent":
                turn["agent_name"] = "ConsoleBot"

    reporter.generate_report(scenario, mock_results, metadata={}, export_html=False)
    captured = capsys.readouterr()
    assert "ConsoleBot" in captured.out

    # Failure status
    mock_results[0]["metrics"][0]["success"] = False
    mock_results[0]["triage_tag"] = "EXPECTED_FAIL"
    reporter.generate_report(scenario, mock_results, export_html=False)
    captured = capsys.readouterr()
    assert "FAILURE [EXPECTED_FAIL]" in captured.out


def test_cleanup_old_reports_advanced(tmp_path):
    old_dir = config.HTML_REPORTS_DIR
    old_traj = config.TRAJECTORIES_DIR

    config.HTML_REPORTS_DIR = tmp_path / "html"
    config.TRAJECTORIES_DIR = tmp_path / "traj"
    config.HTML_REPORTS_DIR.mkdir()
    config.TRAJECTORIES_DIR.mkdir()

    try:
        f1 = config.HTML_REPORTS_DIR / "old.html"
        f1.write_text("old")
        # Set timestamp to 10 days ago
        os.utime(f1, (0, 0))

        f2 = config.HTML_REPORTS_DIR / "new.html"
        f2.write_text("new")

        reporter.cleanup_old_reports(days=5)

        assert not f1.exists()
        assert f2.exists()

        # Exception handling
        f3 = config.HTML_REPORTS_DIR / "err.html"
        f3.write_text("err")
        os.utime(f3, (0, 0))

        with patch("os.unlink", side_effect=OSError("Unlink failed")):
            with patch("builtins.print") as mock_print:
                reporter.cleanup_old_reports(days=5)
                assert any("Failed to clean up" in str(c) for c in mock_print.call_args_list)
    finally:
        config.HTML_REPORTS_DIR = old_dir
        config.TRAJECTORIES_DIR = old_traj


def test_generate_mermaid_edge():
    # Empty history
    assert reporter.generate_mermaid_trajectory({}) == ""

    # Content not dict
    res = {"conversation_history": [{"role": "agent", "content": "text"}]}
    mermaid = reporter.generate_mermaid_trajectory(res)
    assert "agent" in mermaid


def test_reporter_export_flags(tmp_path, mock_results):
    scenario = {"id": "f1", "title": "Export Test"}
    # Default traj dir
    # Export flags
    with patch("eval_runner.config.TRAJECTORIES_DIR", tmp_path / "t"):
        with patch("eval_runner.config.HTML_REPORTS_DIR", tmp_path / "h"):
            reporter.generate_report(
                scenario, mock_results, export_trajectory=True, export_html=True
            )
            assert (tmp_path / "t").exists()
            assert (tmp_path / "h").exists()


def test_cleanup_dir_missing():
    with patch("eval_runner.config.HTML_REPORTS_DIR", Path("/non/existent/dir")):
        reporter.cleanup_old_reports()


def test_generate_report_fail_mermaid(capsys, mock_results):
    scenario = {"id": "m1", "title": "Mermaid Fail"}
    mock_results[0]["metrics"][0]["success"] = False
    reporter.generate_report(scenario, mock_results, export_html=False)
    captured = capsys.readouterr()
    assert "Trajectory Map (Mermaid)" in captured.out
