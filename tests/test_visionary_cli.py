import pytest
from eval_runner.cli import main
from unittest.mock import patch, MagicMock

def test_install_command():
    with patch("eval_runner.cli.handle_install") as mock_install:
        with patch("sys.argv", ["eval-harness", "install", "telecom-pack"]):
            main()
            mock_install.assert_called_once()

def test_analyze_command():
    with patch("eval_runner.cli.handle_analyze") as mock_analyze:
        with patch("sys.argv", ["eval-harness", "analyze", "https://github.com/test"]):
            main()
            mock_analyze.assert_called_once()

def test_ci_generate_command():
    with patch("eval_runner.cli.handle_ci_generate") as mock_ci:
        with patch("sys.argv", ["eval-harness", "ci", "generate"]):
            main()
            mock_ci.assert_called_once()

def test_explain_command():
    with patch("eval_runner.cli.handle_explain") as mock_explain:
        with patch("sys.argv", ["eval-harness", "explain", "runs/run.jsonl"]):
            main()
            mock_explain.assert_called_once()

def test_failures_search_command():
    with patch("eval_runner.cli.handle_failures_search") as mock_failures:
        with patch("sys.argv", ["eval-harness", "failures", "search", "pii"]):
            main()
            mock_failures.assert_called_once()
