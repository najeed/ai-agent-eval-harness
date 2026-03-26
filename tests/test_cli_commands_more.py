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
# --- handle_spec_to_eval (1087, 1117-1119) ---
@pytest.mark.asyncio
async def test_handle_spec_to_eval_exceptions(mock_args, tmp_path, monkeypatch):
    from eval_runner.cli import handle_spec_to_eval
    monkeypatch.chdir(tmp_path)
    mock_args.input = "ghost.md"
    mock_args.output = None
    mock_args.fill_defaults = False
    
    # input missing
    await handle_spec_to_eval(mock_args)
        
    # Auto-filling classification and writing to default path (1117-1119)
    input_file = tmp_path / "real.md"
    input_file.write_text("# Demo", encoding="utf-8")
    mock_args.input = str(input_file)
    mock_open = MagicMock()
    with patch("builtins.open", mock_open), \
         patch("eval_runner.spec_parser.parse_markdown_to_scenario", return_value={"title": "demo"}), \
         patch("eval_runner.cli.classify_scenario", return_value={"industry": "finance", "use_case": "Support", "core_function": "Help"}), \
         patch("eval_runner.spec_parser.save_scenario_stub"):
         await handle_spec_to_eval(mock_args)

# --- handle_mutate (1152-1153, 1161) ---
def test_handle_mutate_exceptions(mock_args, tmp_path, monkeypatch):
    from eval_runner.cli import handle_mutate
    monkeypatch.chdir(tmp_path)
    mock_args.input = "ghost.json"
    mock_args.type = "typo"
    mock_args.output = None
    
    handle_mutate(mock_args)
        
    input_file = tmp_path / "real.json"
    input_file.write_text('{"t": 1}', encoding="utf-8")
    mock_args.input = str(input_file)
    with patch("eval_runner.mutator.mutate_scenario", return_value={}), \
         patch("eval_runner.mutator.save_mutated_scenario"):
         handle_mutate(mock_args)

# --- handle_failures_search ---
def test_handle_failures_search_basic(mock_args, tmp_path, monkeypatch):
    from eval_runner.cli import handle_failures_search
    monkeypatch.chdir(tmp_path)
    mock_args.query = "error"
    
    # Missing/no matches
    handle_failures_search(mock_args)
        
    # Matches > 10
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    for i in range(12):
        (runs_dir / f"r{i}.jsonl").write_text("error inside file", encoding="utf-8")
    
    handle_failures_search(mock_args)

# --- handle_explain ---
def test_handle_explain_basic(mock_args, tmp_path, monkeypatch):
    from eval_runner.cli import handle_explain
    monkeypatch.chdir(tmp_path)
    mock_args.path = "ghost.jsonl"
    handle_explain(mock_args)
        
    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")
    mock_args.path = str(real_file)
    with patch("eval_runner.explainer.explain_trace", return_value={
             "confidence": 0.9, "index": 5, "root_cause": "cpu", "suggestion": "fix"
         }):
         handle_explain(mock_args)

# --- handle_calibrate (1302-1366) ---
def test_handle_calibrate_basic(mock_args, tmp_path, monkeypatch):
    from eval_runner.cli import handle_calibrate
    monkeypatch.chdir(tmp_path)
    mock_args.path = "ghost.jsonl"
    handle_calibrate(mock_args)
        
    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")
    mock_args.path = str(real_file)
    
    # Read Exception
    with patch("eval_runner.cli.load_events", side_effect=Exception("Read bad")):
         handle_calibrate(mock_args)
         
    # No pairs
    with patch("eval_runner.cli.load_events", return_value=[{"event": "start"}]):
         handle_calibrate(mock_args)
         
    # Full pairs > 0.9 (Excellent)
    with patch("eval_runner.cli.load_events", return_value=[
             {"event": "evaluation", "metric": "luna_judge_score", "value": 0.9, "human_score": 0.9},
             {"event": "evaluation", "metric": "luna_judge_score", "value": 0.8, "human_score": 0.8},
         ]):
         handle_calibrate(mock_args)
