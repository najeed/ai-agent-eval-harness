"""
test_cli_commands_more.py

Unit tests for specialized CLI commands (spec-to-eval, mutate, failures, explain, calibrate).
Refactored to eliminate "Mock Namespaces" and use real argparse objects.
"""

import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner import cli

def parse_args(cmd_list):
    """Helper to get a real argparse Namespace for a command."""
    parser = cli.get_parser(is_help=True)
    return parser.parse_args(cmd_list)

# --- handle_spec_to_eval ---
@pytest.mark.asyncio
async def test_handle_spec_to_eval_exceptions(tmp_path, monkeypatch):
    from eval_runner.handlers.scenarios import handle_spec_to_eval
    monkeypatch.chdir(tmp_path)
    
    # input missing (real parser will catch this or we handle it in code)
    args = parse_args(["spec-to-eval", "--input", "ghost.md"])
    await handle_spec_to_eval(args)
        
    # Valid md for parsing
    input_file = tmp_path / "real.md"
    input_file.write_text("# Demo", encoding="utf-8")
    
    args = parse_args(["spec-to-eval", "--input", str(input_file)])
    
    with patch("builtins.open", MagicMock()), \
         patch("eval_runner.spec_parser.parse_markdown_to_scenario", return_value={"title": "demo"}), \
         patch("eval_runner.handlers.scenarios.classify_scenario", return_value={"industry": "finance", "use_case": "Support", "core_function": "Help"}), \
         patch("eval_runner.handlers.scenarios.spec_parser.save_scenario_json", side_effect=Exception("Conversion failed")):
         from eval_runner.handlers.scenarios import handle_spec_to_eval
         with pytest.raises(Exception, match="Conversion failed"):
             await handle_spec_to_eval(args)

# --- handle_mutate ---
def test_handle_mutate_exceptions(tmp_path, monkeypatch):
    from eval_runner.handlers.scenarios import handle_mutate
    monkeypatch.chdir(tmp_path)
    
    args = parse_args(["mutate", "--input", "ghost.json", "--type", "typo"])
    handle_mutate(args)
        
    # Valid v1.2 JSON
    input_file = tmp_path / "real.json"
    input_file.write_text(json.dumps({
        "aes_version": 1.2,
        "metadata": {"name": "Mutate Me", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task"}],
            "edges": []
        }
    }), encoding="utf-8")
    
    args = parse_args(["mutate", "--input", str(input_file), "--type", "typo"])
    with patch("eval_runner.mutator.mutate_scenario", return_value={}), \
         patch("eval_runner.mutator.save_mutated_scenario"):
         handle_mutate(args)

# --- handle_failures_search ---
def test_handle_failures_search_basic(tmp_path, monkeypatch):
    from eval_runner.handlers.environment import handle_failures_search
    monkeypatch.chdir(tmp_path)
    
    args = parse_args(["failures", "search", "error"])
    handle_failures_search(args)
        
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    for i in range(12):
        (runs_dir / f"r{i}.jsonl").write_text("error inside file", encoding="utf-8")
    
    with patch("eval_runner.configuration.RUN_LOG_DIR", runs_dir):
        handle_failures_search(args)

# --- handle_explain ---
def test_handle_explain_basic(tmp_path, monkeypatch):
    from eval_runner.handlers.analysis import handle_explain
    monkeypatch.chdir(tmp_path)
    
    args = parse_args(["explain", "--path", "ghost.jsonl"])
    handle_explain(args)
        
    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")
    
    args = parse_args(["explain", "--path", str(real_file)])
    with patch("eval_runner.explainer.explain_trace", return_value={
             "confidence": 0.9, "root_cause": "cpu", "suggestion": "fix"
         }):
         handle_explain(args)

# --- handle_calibrate ---
def test_handle_calibrate_basic(tmp_path, monkeypatch):
    from eval_runner.handlers.analysis import handle_calibrate
    monkeypatch.chdir(tmp_path)
    
    args = parse_args(["calibrate", "--path", "ghost.jsonl"])
    handle_calibrate(args)
        
    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")
    
    args = parse_args(["calibrate", "--path", str(real_file)])
    
    with patch("eval_runner.handlers.analysis.trace_utils.load_events", side_effect=Exception("Read bad")):
         handle_calibrate(args)
         
    with patch("eval_runner.handlers.analysis.trace_utils.load_events", return_value=[{"event": "start"}]):
         handle_calibrate(args)
         
    with patch("eval_runner.handlers.analysis.trace_utils.load_events", return_value=[
             {"event": "evaluation", "metric": "luna_judge_score", "value": 0.9, "human_score": 0.9},
             {"event": "evaluation", "metric": "luna_judge_score", "value": 0.8, "human_score": 0.8},
         ]):
         handle_calibrate(args)
