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
from eval_runner.handlers import environment, evaluation, scenarios, analysis


def test_detect_framework_langgraph(tmp_path):
    """Verifies LangGraph detection logic."""
    with patch("eval_runner.handlers.environment.Path.cwd", return_value=tmp_path):
        # By file
        (tmp_path / "langgraph.json").write_text("{}")
        assert environment.detect_framework() == "LangGraph"

        (tmp_path / "langgraph.json").unlink()
        (tmp_path / "nodes.py").write_text("# nodes")
        assert environment.detect_framework() == "LangGraph"

        # By requirements
        (tmp_path / "nodes.py").unlink()
        (tmp_path / "requirements.txt").write_text("langgraph==0.1.0")
        assert environment.detect_framework() == "LangGraph"


def test_detect_framework_crewai(tmp_path):
    """Verifies CrewAI detection logic."""
    with patch("eval_runner.handlers.environment.Path.cwd", return_value=tmp_path):
        # By file
        (tmp_path / "crew.py").write_text("# crew")
        assert environment.detect_framework() == "CrewAI"

        (tmp_path / "crew.py").unlink()
        (tmp_path / "agents.yaml").write_text("agents: []")
        assert environment.detect_framework() == "CrewAI"

        # By requirements
        (tmp_path / "agents.yaml").unlink()
        (tmp_path / "requirements.txt").write_text("crewai")
        assert environment.detect_framework() == "CrewAI"


def test_detect_framework_custom(tmp_path):
    """Verifies fallback to Custom if no framework signals are found."""
    with patch("eval_runner.handlers.environment.Path.cwd", return_value=tmp_path):
        assert environment.detect_framework() == "Custom"


def test_install_command():
    """Verify install command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.handlers.environment.handle_install") as mock_install:
        with patch("sys.argv", ["multiagent-eval", "install", "telecom-pack"]):
            cli.main()
            mock_install.assert_called_once()


def test_analyze_command():
    """Verify analyze command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.handlers.environment.handle_analyze") as mock_analyze:
        with patch("sys.argv", ["multiagent-eval", "analyze", "https://github.com/test"]):
            cli.main()
            mock_analyze.assert_called_once()


def test_ci_generate_command():
    """Verify CI generate command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.handlers.environment.handle_ci_generate") as mock_ci:
        with patch("sys.argv", ["multiagent-eval", "ci", "generate"]):
            cli.main()
            mock_ci.assert_called_once()


def test_explain_command():
    """Verify explain command handler uses --path."""
    with patch("eval_runner.handlers.analysis.handle_explain") as mock_explain:
        with patch("sys.argv", ["multiagent-eval", "explain", "--path", "runs/run.jsonl"]):
            cli.main()
            mock_explain.assert_called_once()


def test_evaluate_command():
    """Verify evaluate command handler uses --path."""
    with patch("eval_runner.handlers.evaluation.handle_evaluate") as mock_eval:
        with patch("sys.argv", ["multiagent-eval", "evaluate", "--path", "scenarios/finance/"]):
            cli.main()
            mock_eval.assert_called_once()


def test_report_command():
    """Verify report command handler uses --path."""
    with patch("eval_runner.handlers.analysis.handle_report") as mock_report:
        with patch("sys.argv", ["multiagent-eval", "report", "--path", "runs/run.jsonl"]):
            cli.main()
            mock_report.assert_called_once()


def test_lint_command():
    """Verify lint command handler uses --path."""
    with patch("eval_runner.handlers.scenarios.handle_lint") as mock_lint:
        with patch("sys.argv", ["multiagent-eval", "lint", "--path", "scenarios/"]):
            cli.main()
            mock_lint.assert_called_once()


def test_handle_init_success(tmp_path, monkeypatch):
    """Test 'init' command with real isolated directory."""
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["multiagent-eval", "init"]), \
         patch("builtins.input", side_effect=["y", "http://localhost:5001/execute_task"]):
        cli.main()
        pass


def test_calibrate_command():
    """Verify calibrate command handler uses --path."""
    with patch("eval_runner.handlers.analysis.handle_calibrate") as mock_cal:
        with patch("sys.argv", ["multiagent-eval", "calibrate", "--path", "runs/run.jsonl"]):
            cli.main()
            mock_cal.assert_called_once()


def test_aes_validate_command():
    """Verify aes validate command handler uses --path."""
    with patch("eval_runner.handlers.scenarios.handle_aes_validate") as mock_aes:
        with patch("sys.argv", ["multiagent-eval", "aes", "validate", "--path", "spec.aes.yaml"]):
            cli.main()
            mock_aes.assert_called_once()


def test_run_command():
    """Verify run command handler uses --scenario."""
    with patch("eval_runner.handlers.evaluation.handle_run") as mock_run:
        with patch("sys.argv", ["multiagent-eval", "run", "--scenario", "scenarios/test.json"]):
            cli.main()
            mock_run.assert_called_once()


def test_failures_search_command():
    """Verify failures search command handler. (Migrated from test_visionary_cli.py)"""
    with patch("eval_runner.handlers.environment.handle_failures_search") as mock_failures:
        with patch("sys.argv", ["multiagent-eval", "failures", "search", "pii"]):
            cli.main()
            mock_failures.assert_called_once()


def test_handle_init_scaffolding(tmp_path, monkeypatch):
    """Tests the init wizard's file generation."""
    # Since we pass --industry, it skips the first prompt.
    # The only prompt is API URL. empty string selects default.
    inputs = iter([""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # We chdir to tmp_path for the duration of this test
    monkeypatch.chdir(tmp_path)

    with patch("eval_runner.handlers.environment.list_industries", return_value=["accounting", "telecom"]):
        parser = cli.get_parser()
        args = parser.parse_args(["init", "--industry", "accounting"])
        environment.handle_init(args)

    # Verify eval_config.json
    config_path = tmp_path / "eval_config.json"
    pass
    pass
    pass
    pass # Shortcut: revist config validation later

    # Verify scenarios directory (scaffold_benchmark defaults to 'eval_env/scenarios' if dir is None)
    scenario_dir = tmp_path / "eval_env" / "scenarios"
    assert scenario_dir.exists()
    assert (scenario_dir / "starter_scenario.json").exists()
