import pytest
import os
import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_args():
    return MagicMock()

# --- handle_spec_to_eval (1087, 1117-1119) ---
def test_handle_spec_to_eval_exceptions(mock_args):
    from eval_runner.cli import handle_spec_to_eval
    mock_args.input = "ghost.md"
    mock_args.output = None
    mock_args.fill_defaults = False
    
    # 1087: input missing
    with patch("eval_runner.cli.Path.exists", return_value=False):
        handle_spec_to_eval(mock_args)
        
    # Auto-filling classification and writing to default path (1117-1119)
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("builtins.open"), \
         patch("eval_runner.spec_parser.parse_markdown_to_scenario", return_value={"title": "demo"}), \
         patch("eval_runner.cli.classify_scenario", return_value={"industry": "finance", "use_case": "Support", "core_function": "Help"}), \
         patch("eval_runner.spec_parser.save_scenario_stub"):
         handle_spec_to_eval(mock_args)

# --- handle_import_drift (1142-1143) ---
def test_handle_import_drift_exceptions(mock_args):
    from eval_runner.cli import handle_import_drift
    mock_args.input = "in"
    mock_args.industry = "ind"
    mock_args.output_dir = "out"
    
    with patch("eval_runner.drift_importer.import_trace_as_scenario", side_effect=Exception("Disk bad")):
        handle_import_drift(mock_args)

# --- handle_mutate (1152-1153, 1161) ---
def test_handle_mutate_exceptions(mock_args):
    from eval_runner.cli import handle_mutate
    mock_args.input = "ghost.json"
    mock_args.type = "typo"
    mock_args.output = None
    
    with patch("eval_runner.cli.Path.exists", return_value=False):
        handle_mutate(mock_args)
        
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("builtins.open", return_value=io.StringIO('{"t": 1}')), \
         patch("eval_runner.mutator.mutate_scenario", return_value={}), \
         patch("eval_runner.mutator.save_mutated_scenario"):
         handle_mutate(mock_args)

# --- handle_export (1189-1190) ---
def test_handle_export_basic(mock_args):
    from eval_runner.cli import handle_export
    mock_args.format = "hf"
    mock_args.input = "i"
    mock_args.output = "o"
    with patch("eval_runner.exporter.HFExporter.export") as mock_export:
        handle_export(mock_args)
        mock_export.assert_called()

# --- handle_failures_search ---
def test_handle_failures_search_basic(mock_args):
    from eval_runner.cli import handle_failures_search
    mock_args.query = "error"
    
    # Missing/no matches
    with patch("eval_runner.cli.Path.glob", return_value=[]):
        handle_failures_search(mock_args)
        
    # Matches > 10
    files = [MagicMock() for _ in range(12)]
    # We patch open to return a string matching the query
    with patch("eval_runner.cli.Path.glob", return_value=files), \
         patch("builtins.open", side_effect=[io.StringIO("error inside file")] * 12):
         handle_failures_search(mock_args)

# --- handle_explain ---
def test_handle_explain_basic(mock_args):
    from eval_runner.cli import handle_explain
    mock_args.path = "ghost.jsonl"
    
    with patch("eval_runner.cli.Path.exists", return_value=False):
        handle_explain(mock_args)
        
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.explainer.explain_trace", return_value={
             "confidence": 0.9, "index": 5, "root_cause": "cpu", "suggestion": "fix"
         }):
         handle_explain(mock_args)

# --- handle_calibrate (1302-1366) ---
def test_handle_calibrate_basic(mock_args):
    from eval_runner.cli import handle_calibrate
    mock_args.path = "ghost.jsonl"
    
    # NOT exists
    with patch("eval_runner.cli.Path.exists", return_value=False):
        handle_calibrate(mock_args)
        
    # Read Exception
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", side_effect=Exception("Read bad")):
         handle_calibrate(mock_args)
         
    # No pairs
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", return_value=[{"event": "start"}]):
         handle_calibrate(mock_args)
         
    # Full pairs > 0.9 (Excellent), 0.7 (Good), < 0.7 (Poor)
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", return_value=[
             {"event": "evaluation", "metric": "luna_judge_score", "value": 0.9, "human_score": 0.9},
             {"event": "evaluation", "metric": "luna_judge_score", "value": 0.8, "human_score": 0.8},
         ]):
         handle_calibrate(mock_args)
         
    # Poor pairing correlation (e.g. anti-correlated)
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", return_value=[
             {"event": "evaluation", "metric": "luna_judge_score", "value": 1.0, "human_score": 0.0},
             {"event": "evaluation", "metric": "luna_judge_score", "value": 0.0, "human_score": 1.0},
         ]):
         handle_calibrate(mock_args)
