import pytest
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval_runner import cli


@pytest.fixture
def cli_runner(tmp_path, monkeypatch):
    """Fixture to run CLI commands in a temporary directory."""
    monkeypatch.chdir(tmp_path)
    # Ensure necessary directories exist
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "industries").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "runs").mkdir()
    return tmp_path


def test_handle_list_integration(cli_runner):
    """Integrates handle_list with ScenarioCatalog."""
    with patch("eval_runner.catalog.ScenarioCatalog.load_index") as mock_load, patch(
        "eval_runner.catalog.list_scenarios"
    ) as mock_list:

        with patch("sys.argv", ["eval-harness", "list"]):
            cli.main()
            mock_load.assert_called_once()
            mock_list.assert_called_once()


def test_handle_lint_integration(cli_runner):
    """Integrates handle_lint with linter."""
    scenario_path = cli_runner / "scenarios" / "test.json"
    scenario_path.write_text("{}")

    with patch("eval_runner.linter.run_lint") as mock_lint:
        with patch("sys.argv", ["eval-harness", "lint", "--path", str(scenario_path)]):
            cli.main()
            mock_lint.assert_called_once_with(str(scenario_path))


def test_handle_report_integration(cli_runner):
    """Integrates handle_report with reporter."""
    trace_path = cli_runner / "runs" / "run.jsonl"
    trace_path.write_text(json.dumps({"event": "run_start", "run_id": "r1", "scenario": "s1"}) + "\n")

    with patch("eval_runner.reporter.generate_html_report", return_value="report.html") as mock_gen:
        with patch("sys.argv", ["eval-harness", "report", "--path", str(trace_path)]):
            cli.main()
            mock_gen.assert_called_once()


def test_handle_aes_validate_integration(cli_runner):
    """Integrates handle_aes_validate with jsonschema."""
    # Mock schema file
    schema_dir = Path(cli.__file__).parent.parent / "spec" / "aes"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "aes.schema.json").write_text("{}")

    aes_file = cli_runner / "test.aes.yaml"
    aes_file.write_text("scenario_id: test")

    with patch("jsonschema.validate") as mock_val:
        with patch("sys.argv", ["eval-harness", "aes", "validate", "--path", str(aes_file)]):
            cli.main()
            mock_val.assert_called_once()


def test_handle_cleanup_runs_integration(cli_runner, monkeypatch):
    """Integrates handle_cleanup_runs logic."""
    old_file = cli_runner / "runs" / "old.jsonl"
    old_file.write_text("old")
    # Backdate the file (more than 7 days)
    import time

    old_time = time.time() - (10 * 86400)
    os.utime(old_file, (old_time, old_time))

    # Mock confirmation to 'y'
    monkeypatch.setattr("builtins.input", lambda _: "y")

    with patch("sys.argv", ["eval-harness", "cleanup-runs", "--days", "7"]):
        cli.main()
        assert not old_file.exists()


def test_handle_install_integration(cli_runner):
    """Integrates handle_install logic."""
    with patch("sys.argv", ["eval-harness", "install", "telecom-pack"]):
        cli.main()
        assert (cli_runner / "industries" / "telecom").exists()


def test_handle_ci_generate_integration(cli_runner):
    """Integrates handle_ci_generate logic."""
    with patch("sys.argv", ["eval-harness", "ci", "generate"]):
        cli.main()
        assert (cli_runner / ".github" / "workflows" / "agent_eval.yml").exists()


def test_handle_failures_search_integration(cli_runner):
    """Integrates handle_failures_search logic."""
    scen_file = cli_runner / "industries" / "finance" / "bad.json"
    scen_file.parent.mkdir(parents=True)
    scen_file.write_text('{"content": "credit card failure"}')

    with patch("sys.argv", ["eval-harness", "failures", "search", "credit"]):
        cli.main()
        # Coverage check


def test_handle_spec_to_eval_integration(cli_runner):
    """Integrates handle_spec_to_eval logic."""
    md_file = cli_runner / "spec.md"
    md_file.write_text("# Test Spec\nScenario ID: s123\n")

    # Mock classifier to avoid torch dependency in tests
    with patch("eval_runner.cli.classify_scenario") as mock_class:
        mock_class.return_value = {"industry": "finance", "use_case": "U1", "core_function": "F1"}
        with patch("sys.argv", ["eval-harness", "spec-to-eval", "--input", str(md_file), "--output", "s123.json"]):
            cli.main()
            assert (cli_runner / "s123.json").exists()


def test_handle_mutate_integration(cli_runner):
    """Integrates handle_mutate logic."""
    scen_file = cli_runner / "scen.json"
    scen_file.write_text(json.dumps({"scenario_id": "s1", "description": "test"}))

    with patch("eval_runner.mutator.mutate_scenario") as mock_mutate:
        mock_mutate.return_value = {"scenario_id": "s1_mut", "description": "mutated"}
        with patch("sys.argv", ["eval-harness", "mutate", "--input", str(scen_file), "--type", "typo"]):
            cli.main()
            assert (cli_runner / "scen_typo.json").exists()
