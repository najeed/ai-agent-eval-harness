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


def test_reporter_truthfulness_no_file_existence_verification(tmp_path, monkeypatch):
    """HTML report does NOT display VERIFIED RUN merely because a manifest exists on disk."""
    monkeypatch.setattr(config, "HTML_REPORTS_DIR", tmp_path / "reports")
    scenario = {"id": "s1", "title": "Test Scenario"}
    results = [
        {
            "task_id": "t1",
            "metrics": [{"metric": "m1", "score": 1, "threshold": 0.5, "success": True}],
        }
    ]

    run_dir = tmp_path / "runs" / "run-unverified"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "audit_manifest.json").write_text("{}", encoding="utf-8")
    (run_dir / "trace.jsonl").write_text("{}", encoding="utf-8")

    out_file = reporter.generate_html_report(
        scenario, results, metadata={"run_id": "run-unverified"}
    )
    html = Path(out_file).read_text(encoding="utf-8")
    assert "VERIFIED RUN" not in html

    out_file_verified = reporter.generate_html_report(
        scenario,
        results,
        metadata={
            "run_id": "run-verified",
            "verification_result": {"is_valid": True, "status": "CERTIFIED"},
        },
    )
    html_verified = Path(out_file_verified).read_text(encoding="utf-8")
    assert "VERIFIED RUN" in html_verified


def test_reporter_full_coverage_matrix(tmp_path, monkeypatch, capsys):
    """Exhaustive test coverage for remaining branches in eval_runner/reporter.py."""
    monkeypatch.setattr(config, "HTML_REPORTS_DIR", tmp_path / "html_reports")

    # 1. _generate_mermaid_dag with short agent name (<= 20 chars) and non-standard role
    res_short = {
        "conversation_history": [
            {"role": "agent", "content": {"action": "act"}, "agent": "http://short"},
            {"role": "system", "content": "system prompt"},  # non-agent, non-environment
            {"role": "environment", "content": {"status": "success"}},
        ]
    }
    dag = reporter.generate_mermaid_trajectory(res_short)
    assert "(short)" in dag
    assert "..." not in dag

    # 2. generate_html_report with verification_result as bool
    scen = {"id": "s_bool", "title": "Bool Test"}
    out_bool_t = reporter.generate_html_report(scen, [], metadata={"verification_result": True})
    assert "VERIFIED RUN" in Path(out_bool_t).read_text(encoding="utf-8")
    out_bool_f = reporter.generate_html_report(scen, [], metadata={"verification_result": False})
    assert "VERIFIED RUN" not in Path(out_bool_f).read_text(encoding="utf-8")

    # 3. generate_html_report with verification_package object and dict
    class MockPkgSuccess:
        def verify_completeness(self):
            return True

        def verify_signature(self):
            return True

    class MockPkgError:
        def verify_completeness(self):
            return True

        def verify_signature(self):
            raise RuntimeError("Signature verification crash")

    out_pkg_ok = reporter.generate_html_report(
        scen, [], metadata={"verification_package": MockPkgSuccess()}
    )
    assert "VERIFIED RUN" in Path(out_pkg_ok).read_text(encoding="utf-8")

    out_pkg_err = reporter.generate_html_report(
        scen, [], metadata={"verification_package": MockPkgError()}
    )
    assert "VERIFIED RUN" not in Path(out_pkg_err).read_text(encoding="utf-8")

    out_pkg_str = reporter.generate_html_report(
        scen, [], metadata={"verification_package": "string_not_pkg"}
    )
    assert "VERIFIED RUN" not in Path(out_pkg_str).read_text(encoding="utf-8")

    out_pkg_dict = reporter.generate_html_report(
        scen, [], metadata={"verification_package": {"status": "CERTIFIED", "verified": True}}
    )
    assert "VERIFIED RUN" in Path(out_pkg_dict).read_text(encoding="utf-8")

    out_pkg_unverif = reporter.generate_html_report(
        scen, [], metadata={"verification_package": {"status": "UNVERIFIED", "verified": False}}
    )
    assert "VERIFIED RUN" not in Path(out_pkg_unverif).read_text(encoding="utf-8")

    # 4. generate_html_report with protocol local and socket, and agent discovery
    monkeypatch.setenv("AGENT_LOCAL_CMD", "python agent.py")
    monkeypatch.setenv("AGENT_SOCKET_ADDR", "localhost:9999")

    results_with_agent = [
        {
            "task_id": "t1",
            "metrics": [{"metric": "m1", "score": 1.0, "threshold": 0.5, "success": True}],
            "conversation_history": [
                {"role": "agent", "agent_name": "DiscoveredAgent", "content": {"action": "think"}}
            ],
        },
        {"workflow_verdict": {"status": "completed"}},  # non-task verdict row (branch 236)
    ]

    out_local = reporter.generate_html_report(
        scen, results_with_agent, metadata={"protocol": "local", "agent": "unknown"}
    )
    assert "DiscoveredAgent" in Path(out_local).read_text(encoding="utf-8")

    out_socket = reporter.generate_html_report(
        scen, results_with_agent, metadata={"protocol": "socket", "agent": None}
    )
    assert "DiscoveredAgent" in Path(out_socket).read_text(encoding="utf-8")

    out_custom_proto = reporter.generate_html_report(
        scen, results_with_agent, metadata={"protocol": "custom", "agent": None}
    )
    assert "DiscoveredAgent" in Path(out_custom_proto).read_text(encoding="utf-8")

    # Explicit agent & agent_name already in metadata (branches 184->192, 201->210)
    out_explicit = reporter.generate_html_report(
        scen,
        results_with_agent,
        metadata={"agent": "ExplicitAgent", "agent_name": "ExplicitName", "protocol": "http"},
    )
    assert "ExplicitName" in Path(out_explicit).read_text(encoding="utf-8")

    # 5. Multi-attempt HTML report
    multi_results = [
        [
            {
                "task_id": "t1",
                "metrics": [{"metric": "m1", "score": 1.0, "threshold": 0.5, "success": True}],
            },
            {"synthetic": True},  # non-task verdict row
        ],
        [
            {
                "task_id": "t1",
                "metrics": [{"metric": "m1", "score": 0.0, "threshold": 0.5, "success": False}],
            },
        ],
    ]
    out_multi = reporter.generate_html_report(scen, multi_results)
    assert "Attempt 1 of 2" in Path(out_multi).read_text(encoding="utf-8")

    # 6. generate_report with local/socket protocols, agent discovery, and multi-attempts
    reporter.generate_report(
        scen,
        multi_results,
        export_trajectory=False,
        export_html=False,
        metadata={"protocol": "local", "agent": "Unknown"},
    )
    out_term_local = capsys.readouterr().out
    assert "Protocol: LOCAL" in out_term_local
    assert "Total Attempts (N): 2" in out_term_local

    reporter.generate_report(
        scen,
        [results_with_agent],
        export_trajectory=False,
        export_html=False,
        metadata={"protocol": "socket", "agent": None},
    )
    out_term_sock = capsys.readouterr().out
    assert "Protocol: SOCKET" in out_term_sock
    assert "DiscoveredAgent" in out_term_sock

    reporter.generate_report(
        scen,
        [results_with_agent],
        export_trajectory=False,
        export_html=False,
        metadata={"protocol": "custom", "agent": None},
    )
    capsys.readouterr()

    # Explicit agent & agent_name in metadata for terminal report (branches 454->462, 469->481)
    reporter.generate_report(
        scen,
        [results_with_agent],
        export_trajectory=False,
        export_html=False,
        metadata={"agent": "ExplicitAgent", "agent_name": "ExplicitName", "protocol": "http"},
    )
    out_term_exp = capsys.readouterr().out
    assert "Agent: ExplicitName" in out_term_exp
