"""
test_cli.py

Unit tests for the Onboarding CLI (eval_runner.cli).
Updated for subparser architecture and robustness.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from eval_runner import cli


def test_detect_framework_langgraph(tmp_path):
    """Verifies LangGraph detection logic."""
    with patch("eval_runner.cli.Path.cwd", return_value=tmp_path):
        # By file
        (tmp_path / "langgraph.json").write_text("{}")
        assert cli.detect_framework() == "LangGraph"

        (tmp_path / "langgraph.json").unlink()
        (tmp_path / "nodes.py").write_text("# nodes")
        assert cli.detect_framework() == "LangGraph"

        # By requirements
        (tmp_path / "nodes.py").unlink()
        (tmp_path / "requirements.txt").write_text("langgraph==0.1.0")
        assert cli.detect_framework() == "LangGraph"


def test_detect_framework_crewai(tmp_path):
    """Verifies CrewAI detection logic."""
    with patch("eval_runner.cli.Path.cwd", return_value=tmp_path):
        # By file
        (tmp_path / "crew.py").write_text("# crew")
        assert cli.detect_framework() == "CrewAI"

        (tmp_path / "crew.py").unlink()
        (tmp_path / "agents.yaml").write_text("agents: []")
        assert cli.detect_framework() == "CrewAI"

        # By requirements
        (tmp_path / "agents.yaml").unlink()
        (tmp_path / "requirements.txt").write_text("crewai")
        assert cli.detect_framework() == "CrewAI"


def test_detect_framework_custom(tmp_path):
    """Verifies fallback to Custom if no framework signals are found."""
    with patch("eval_runner.cli.Path.cwd", return_value=tmp_path):
        assert cli.detect_framework() == "Custom"


def test_install_command():
    """Verify install command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.cli.handle_install") as mock_install:
        with patch("sys.argv", ["eval-harness", "install", "telecom-pack"]):
            cli.main()
            mock_install.assert_called_once()


def test_analyze_command():
    """Verify analyze command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.cli.handle_analyze") as mock_analyze:
        with patch("sys.argv", ["eval-harness", "analyze", "https://github.com/test"]):
            cli.main()
            mock_analyze.assert_called_once()


def test_ci_generate_command():
    """Verify CI generate command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.cli.handle_ci_generate") as mock_ci:
        with patch("sys.argv", ["eval-harness", "ci", "generate"]):
            cli.main()
            mock_ci.assert_called_once()


def test_explain_command():
    """Verify explain command handler uses --path."""
    with patch("eval_runner.cli.handle_explain") as mock_explain:
        with patch("sys.argv", ["eval-harness", "explain", "--path", "runs/run.jsonl"]):
            cli.main()
            mock_explain.assert_called_once()


def test_evaluate_command():
    """Verify evaluate command handler uses --path."""
    with patch("eval_runner.cli.run_evaluate") as mock_eval:
        with patch(
            "sys.argv", ["eval-harness", "evaluate", "--path", "scenarios/finance/"]
        ):
            cli.main()
            mock_eval.assert_called_once()


def test_report_command():
    """Verify report command handler uses --path."""
    with patch("eval_runner.cli.handle_report") as mock_report:
        with patch("sys.argv", ["eval-harness", "report", "--path", "runs/run.jsonl"]):
            cli.main()
            mock_report.assert_called_once()


def test_lint_command():
    """Verify lint command handler uses --path."""
    with patch("eval_runner.cli.handle_lint") as mock_lint:
        with patch("sys.argv", ["eval-harness", "lint", "--path", "scenarios/"]):
            cli.main()
            mock_lint.assert_called_once()


def test_calibrate_command():
    """Verify calibrate command handler uses --path."""
    with patch("eval_runner.cli.handle_calibrate") as mock_cal:
        with patch(
            "sys.argv", ["eval-harness", "calibrate", "--path", "runs/run.jsonl"]
        ):
            cli.main()
            mock_cal.assert_called_once()


def test_aes_validate_command():
    """Verify aes validate command handler uses --path."""
    with patch("eval_runner.cli.handle_aes_validate") as mock_aes:
        with patch(
            "sys.argv", ["eval-harness", "aes", "validate", "--path", "spec.aes.yaml"]
        ):
            cli.main()
            mock_aes.assert_called_once()


def test_run_command():
    """Verify run command handler uses --scenario."""
    with patch("eval_runner.cli.run_scenario") as mock_run:
        with patch(
            "sys.argv", ["eval-harness", "run", "--scenario", "scenarios/test.json"]
        ):
            cli.main()
            mock_run.assert_called_once()


def test_failures_search_command():
    """Verify failures search command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.cli.handle_failures_search") as mock_failures:
        with patch("sys.argv", ["eval-harness", "failures", "search", "pii"]):
            cli.main()
            mock_failures.assert_called_once()


def test_handle_init_scaffolding(tmp_path, monkeypatch):
    """Tests the init wizard's file generation."""
    # Mock inputs: Industry '1' (accounting), API URL (default)
    inputs = iter(["1", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # We chdir to tmp_path for the duration of this test
    monkeypatch.chdir(tmp_path)

    with patch(
        "eval_runner.cli.list_industries", return_value=["accounting", "telecom"]
    ):
        mock_args = MagicMock()
        mock_args.dir = None
        mock_args.industry = None
        cli.handle_init(mock_args)

    # Verify eval_config.json
    config_path = tmp_path / "eval_config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["industry"] == "accounting"
    assert config["agent_api_url"] == "http://localhost:5001/execute_task"

    # Verify scenarios directory
    scenario_dir = tmp_path / "scenarios"
    assert scenario_dir.exists()
    assert (scenario_dir / "starter_scenario.json").exists()
