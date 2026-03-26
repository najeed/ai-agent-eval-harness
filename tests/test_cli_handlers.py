import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval_runner import cli

@pytest.fixture
def mock_args():
    args = MagicMock()
    args.industry = "finance"
    args.format = "json"
    args.days = 7
    args.input = "input.json"
    args.output_dir = "output"
    args.query = "test"
    return args

def test_handle_list(mock_args):
    """Test 'list' command handler."""
    with patch("eval_runner.catalog.list_scenarios") as mock_list:
        mock_args.search = "test"
        cli.handle_list(mock_args)
        mock_list.assert_called_once_with(query="test")

def test_handle_doctor(mock_args, capsys):
    """Test 'doctor' command handler."""
    with patch("eval_runner.doctor.run_doctor") as mock_run:
        cli.handle_doctor(mock_args)
        # handle_doctor calls asyncio.run(doctor.run_doctor())
        mock_run.assert_called_once()

def test_handle_cleanup_runs(mock_args, tmp_path):
    """Test 'cleanup-runs' command handler with real filesystem operations."""
    import time
    import os
    
    # Setup isolated runs directory
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    old_file = runs_dir / "old.jsonl"
    old_file.write_text("old", encoding="utf-8")
    
    # Backdate the file
    now = time.time()
    past = now - (10 * 86400)
    os.utime(str(old_file), (past, past))
    
    mock_args.days = 5
    mock_args.dir = str(runs_dir)
    
    # Instead of patching Path class, we rely on the command using the path from args
    # or we patch the config if it defaults to a global path.
    # handle_cleanup_runs uses Path("runs") if no path in args? Let's check cli.py
    with patch("eval_runner.cli.input", return_value="y"), \
         patch("eval_runner.config.RUN_LOG_DIR", runs_dir):
        cli.handle_cleanup_runs(mock_args)
    
    assert not old_file.exists()

def test_handle_inspect(mock_args, capsys, tmp_path):
    """Test 'inspect' command handler."""
    scen_path = tmp_path / "scen.json"
    scen_path.write_text(json.dumps({
        "scenario_id": "s1",
        "title": "Inspect Me",
        "description": "desc",
        "use_case": "uc",
        "core_function": "cf",
        "industry": "finance",
        "tasks": [{
            "task_id": "t1", 
            "description": "task", 
            "expected_outcome": "outcome", 
            "success_criteria": [{"metric": "planning_accuracy", "threshold": 0.5}]
        }]
    }))
    mock_args.scenario_path = str(scen_path)
    
    cli.handle_inspect(mock_args)
    captured = capsys.readouterr()
    assert "Inspect Me" in captured.out

def test_handle_lint(mock_args, capsys, tmp_path):
    """Test 'lint' command handler."""
    scen_path = tmp_path / "scen.json"
    scen_path.write_text(json.dumps({
        "scenario_id": "s1",
        "title": "Lint Me",
        "description": "desc",
        "use_case": "uc",
        "core_function": "cf",
        "industry": "finance",
        "tasks": [{
            "task_id": "t1", 
            "description": "task", 
            "expected_outcome": "outcome", 
            "success_criteria": [{"metric": "planning_accuracy", "threshold": 0.5}]
        }]
    }))
    mock_args.target = str(scen_path)
    
    with patch("eval_runner.linter.run_lint") as mock_run_lint:
        cli.handle_lint(mock_args)
        mock_run_lint.assert_called_once_with(str(scen_path))

def test_handle_export(mock_args, capsys):
    """Test 'export' command handler."""
    mock_args.format = "hf"
    mock_args.input = "trace.jsonl"
    mock_args.output = "dataset.json"
    with patch("eval_runner.exporter.HFExporter.export") as mock_export:
        cli.handle_export(mock_args)
        mock_export.assert_called_once_with("trace.jsonl", "dataset.json")

def test_handle_import_drift(mock_args, capsys):
    """Test 'import-drift' command handler."""
    mock_args.input = "trace.jsonl"
    mock_args.industry = "telecom"
    mock_args.output_dir = "scenarios"
    with patch("eval_runner.drift_importer.import_trace_as_scenario") as mock_import:
        cli.handle_import_drift(mock_args)
        mock_import.assert_called_once_with(Path("trace.jsonl"), "telecom", Path("scenarios"))

def test_handle_taxonomy(mock_args, capsys):
    """Test 'taxonomy' command handler."""
    cli.handle_taxonomy(mock_args)
    captured = capsys.readouterr()
    assert "AGENT-EVAL FAILURE TAXONOMY" in captured.out

def test_handle_catalog_search(mock_args, capsys):
    """Test 'catalog-search' command handler."""
    mock_args.query = "pii"
    with patch("eval_runner.catalog.ScenarioCatalog.search") as mock_search:
        mock_search.return_value = [{"id": "s1", "title": "PII Test"}]
        cli.handle_catalog_search(mock_args)
        captured = capsys.readouterr()
        assert "Search results for 'pii'" in captured.out
        assert "s1: PII Test" in captured.out

def test_handle_failures_search(mock_args, capsys, tmp_path, monkeypatch):
    """Test 'failures-search' command handler using real isolated directory."""
    industries_dir = tmp_path / "industries"
    industries_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    
    with patch("eval_runner.config.PROJECT_ROOT", tmp_path):
        cli.handle_failures_search(mock_args)
        captured = capsys.readouterr()
        assert "Searching corpus" in captured.out

def test_handle_triage(mock_args, capsys, tmp_path):
    """Test 'triage' command handler using real filesystem."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_file = runs_dir / "test.jsonl"
    run_file.write_text(json.dumps({"event": "run_start", "run_id": "r1", "scenario": "s1"}), encoding="utf-8")
    
    mock_args.path = str(run_file)
    with patch("eval_runner.trace_utils.load_events", return_value=[{"event": "run_start"}]), \
         patch("eval_runner.triage.TriageEngine.apply_triage") as mock_apply, \
         patch("eval_runner.config.RUN_LOG_DIR", runs_dir):
        cli.handle_triage(mock_args)
        mock_apply.assert_called_once()

def test_handle_explain(mock_args, capsys, tmp_path):
    """Test 'explain' command handler."""
    trace_path = tmp_path / "run.jsonl"
    trace_path.write_text(json.dumps({"event": "agent_response", "content": "error"}))
    mock_args.path = str(trace_path)
    
    with patch("eval_runner.explainer.explain_trace") as mock_explain:
        mock_explain.return_value = {
            "index": 1,
            "confidence": 0.9,
            "root_cause": "Test failure",
            "suggestion": "Test suggestion"
        }
        cli.handle_explain(mock_args)
        captured = capsys.readouterr()
        assert "AGENT-EVAL FORENSIC REPORT" in captured.out
        assert "Test failure" in captured.out

if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
