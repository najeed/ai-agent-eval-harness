import eval_runner
"""
test_cli_extra.py

Unit tests for CLI handlers and specialized commands.
Refactored to eliminate "Mock Namespaces" and use real argparse objects for high-fidelity verification.
"""

import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from eval_runner import cli

def parse_args(cmd_list):
    """Helper to get a real argparse Namespace for a command."""
    parser = cli.get_parser(is_help=True)
    return parser.parse_args(cmd_list)

# --- handle_aes_validate ---
def test_handle_aes_validate_dir(tmp_path, monkeypatch):
    """Test 'aes validate' command with real parser and isolated directory."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scenario.aes.yaml").write_text("scenario_id: test", encoding="utf-8")
    
    args = parse_args(["aes", "validate", "--path", str(tmp_path)])
    
    with patch("yaml.safe_load", return_value={"scenario_id": "test"}), \
         patch("jsonschema.validate"):
        eval_runner.handlers.scenarios.handle_aes_validate(args)


# --- handle_replay ---
def test_handle_replay_success(tmp_path, monkeypatch):
    """Test 'replay' command logic with real parser."""
    monkeypatch.chdir(tmp_path)
    trace_file = tmp_path / "some_trace.jsonl"
    trace_file.write_text("{}", encoding="utf-8")
    
    args = parse_args(["replay", "--path", str(trace_file)])
    
    with patch("eval_runner.handlers.analysis.trace_utils.load_events") as mock_load:
        mock_load.return_value = [
            {"event": "run_start", "run_id": "1", "scenario": "s1"},
            {"event": "prompt", "role": "user", "content": "hi"},
            {"event": "agent_response", "step": 1, "content": "hello"},
            {"event": "tool_call", "tool": "search", "arguments": {}},
            {"event": "tool_result", "tool": "search", "result": "found"},
            {"event": "evaluation", "metric": "acc", "value": 1.0},
            {"event": "run_end", "status": "success"},
        ]
        eval_runner.handlers.evaluation.handle_replay(args)


# --- run_scenario ---
@pytest.mark.asyncio
async def test_handle_run_success(tmp_path, monkeypatch):
    """Test 'run' handler with real parser."""
    monkeypatch.chdir(tmp_path)
    scen_file = tmp_path / "scen.json"
    scen_file.write_text("{}", encoding="utf-8")
    
    args = parse_args(["run", "--scenario", str(scen_file)])
    
    with patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "test"}), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_engine:
         
        mock_engine.return_value = []
        await eval_runner.handlers.evaluation.handle_run(args)
        mock_engine.assert_called_once()


# --- run_evaluate ---
@pytest.mark.asyncio
async def test_run_evaluate_success(tmp_path, monkeypatch):
    """Test 'evaluate' handler with real parser and multiple attempts."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t1.json").write_text("{}", encoding="utf-8")
    log_dir = tmp_path / "logs"
    
    args = parse_args(["evaluate", "--path", str(tmp_path), "--run-log-dir", str(log_dir), "--attempts", "2"])
    
    with patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "t1", "title": "T1"}), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_eval, \
         patch("eval_runner.metrics.calculate_consensus_scoring", return_value=1.0), \
         patch("builtins.open", MagicMock()):
         
            mock_eval.return_value = [
                {"metrics": [{"success": True}], "conversation_history": [{"role": "agent", "content": "done"}]}
            ]
            
            await eval_runner.handlers.evaluation.handle_evaluate(args)


# --- handle_auto_translate ---
@pytest.mark.asyncio
async def test_handle_auto_translate_success(tmp_path, monkeypatch):
    """Test 'auto-translate' with real parser."""
    monkeypatch.chdir(tmp_path)
    in_file = tmp_path / "in.txt"
    in_file.write_text("text")
    
    args = parse_args(["auto-translate", "--input", str(in_file)])
    
    with patch("eval_runner.auto_translate.extract_text", return_value="test text"), \
         patch("eval_runner.auto_translate.translate_to_scenario", new_callable=AsyncMock) as mock_trans, \
         patch("eval_runner.auto_translate.save_scenario") as mock_save:
         
        mock_trans.return_value = {"scenario_id": "auto"}
        await eval_runner.handlers.environment.handle_auto_translate(args)
        mock_save.assert_called_once()


# --- handle_calibrate ---
def test_handle_calibrate_success(tmp_path, monkeypatch):
    """Test 'calibrate' with real parser."""
    monkeypatch.chdir(tmp_path)
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "t1.jsonl").write_text(json.dumps({"event": "evaluation", "metric": "m1", "value": 0.5}))
    
    args = parse_args(["calibrate", "--path", str(trace_dir)])
    
    with patch("eval_runner.handlers.analysis.trace_utils.load_events", return_value=[{"event": "evaluation", "metric": "m1", "value": 0.5}]):
        eval_runner.handlers.analysis.handle_calibrate(args)

def test_handle_calibrate_plot(tmp_path, monkeypatch):
    """Test 'calibrate --plot' with real parser and matplotlib mock."""
    monkeypatch.chdir(tmp_path)
    trace_file = tmp_path / "t1.jsonl"
    trace_file.write_text(json.dumps({"event": "evaluation", "metric": "xyz", "value": 1}))
    
    args = parse_args(["calibrate", "--path", str(trace_file), "--plot"])
    
    mock_plt = MagicMock()
    with patch("eval_runner.handlers.analysis.trace_utils.load_events", return_value=[{"event": "evaluation", "metric": "xyz", "value": 1}]), \
         patch.dict("sys.modules", {"matplotlib": MagicMock(), "matplotlib.pyplot": mock_plt}):
        eval_runner.handlers.analysis.handle_calibrate(args)
