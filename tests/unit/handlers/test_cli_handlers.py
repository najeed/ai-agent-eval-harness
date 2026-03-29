import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner.handlers import environment, scenarios, analysis, evaluation

@pytest.fixture
def mock_args():
    args = MagicMock()
    args.industry = "finance"
    args.format = "json"
    args.days = 7
    args.input = "input.json"
    args.output_dir = "output"
    args.query = "test"
    args.standard = None
    args.scenario_path = "scen.json"
    return args

def test_handle_list(mock_args):
    """Test 'list' command handler. Forensic: Patch ScenarioCatalog to avoid OSError."""
    with patch("eval_runner.handlers.scenarios.catalog.ScenarioCatalog"), \
         patch("eval_runner.handlers.scenarios.catalog.list_scenarios") as mock_list:
        mock_args.search = "test"
        mock_args.refresh = False
        scenarios.handle_list(mock_args)
        mock_list.assert_called_once_with(query="test")

def test_handle_doctor(mock_args, capsys):
    """Test 'doctor' command handler."""
    with patch("eval_runner.handlers.environment.doctor.run_doctor", new_callable=AsyncMock) as mock_run:
        environment.handle_doctor(mock_args)
        mock_run.assert_called_once()

def test_handle_cleanup_runs(mock_args, tmp_path):
    """Test 'cleanup-runs' command handler."""
    with patch("eval_runner.handlers.environment.cleaner.cleanup_traces") as mock_cleanup:
        mock_args.dir = str(tmp_path)
        environment.handle_cleanup_runs(mock_args)
        mock_cleanup.assert_called_once()

def test_handle_inspect(mock_args, capsys, tmp_path):
    """Test 'inspect' command handler. Forensic: v1.2 Numerical Schema + Node desc."""
    scen_path = tmp_path / "scen.json"
    scen_path.write_text(json.dumps({
        "aes_version": 1.2,
        "metadata": {"name": "Inspect Me", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "First Task"}],
            "edges": []
        }
    }))
    mock_args.scenario_path = str(scen_path)
    scenarios.handle_inspect(mock_args)
    captured = capsys.readouterr()
    assert "Inspect Me" in captured.out

def test_handle_lint(mock_args, capsys, tmp_path):
    """Test 'lint' command handler. Forensic: v1.2 Numerical Schema."""
    scen_path = tmp_path / "scen.json"
    scen_path.write_text(json.dumps({
        "aes_version": 1.2,
        "metadata": {"name": "Lint Me", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "Valid Task"}],
            "edges": []
        }
    }))
    mock_args.target = str(scen_path)
    with patch("eval_runner.handlers.scenarios.linter.run_lint") as mock_lint:
        scenarios.handle_lint(mock_args)
        mock_lint.assert_called_once()

def test_handle_export(mock_args, capsys):
    """Test 'export' command handler."""
    mock_args.input = "trace.jsonl"
    mock_args.output = "dataset.json"
    with patch("eval_runner.exporter.HFExporter.export") as mock_export:
        environment.handle_export(mock_args)
        mock_export.assert_called_once_with("trace.jsonl", "dataset.json")

def test_handle_taxonomy(mock_args, capsys):
    """Test 'taxonomy' command handler."""
    analysis.handle_taxonomy(mock_args)
    captured = capsys.readouterr()
    assert "AGENT-EVAL FAILURE TAXONOMY" in captured.out

def test_handle_verify_missing(capsys):
    """Test 'verify' with missing file. Forensic alignment: Uses [CRITICAL] string."""
    args = MagicMock(path="missing.jsonl", manifest=None)
    evaluation.handle_verify(args)
    captured = capsys.readouterr()
    assert "[CRITICAL] FAILED: Trace integrity compromised!" in captured.out

def test_handle_import_drift(mock_args, capsys):
    """Test 'import-drift' command handler. Forensic: Full-stack scenario drift analysis."""
    mock_args.input = "trace.jsonl"
    mock_args.industry = "telecom"
    mock_args.output_dir = "scenarios"
    with patch("eval_runner.handlers.scenarios.drift_importer.import_trace_as_scenario") as mock_import:
        scenarios.handle_import_drift(mock_args)
        mock_import.assert_called_once_with(Path("trace.jsonl"), "telecom", Path("scenarios"))
