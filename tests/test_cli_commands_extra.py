import pytest
import os
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_args():
    args = MagicMock()
    args.format = "jsonl"
    args.run_log_dir = None
    args.per_run_logs = None
    args.master_log = None
    args.seed = None
    args.protocol = "http"
    args.agent = "http://localhost:5000"
    args.agent_cmd = None
    args.agent_socket = None
    args.limit = None
    args.attempts = 1
    return args

# --- handle_report exceptions (513-514, 518-520, 524-526) ---
def test_handle_report_exceptions(tmp_path, monkeypatch):
    from eval_runner.cli import handle_report
    monkeypatch.chdir(tmp_path)
    args = MagicMock()
    args.path = "ghost.jsonl"
    
    # 513-514: File not found
    handle_report(args)
        
    # 518-520: Read error
    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")
    args.path = str(real_file)
    with patch("eval_runner.cli.load_events", side_effect=Exception("Read fail")):
        handle_report(args)

# --- handle_replay exceptions (596-597, 601-603) ---
def test_handle_replay_exceptions(tmp_path, monkeypatch):
    from eval_runner.cli import handle_replay
    monkeypatch.chdir(tmp_path)
    args = MagicMock()
    args.path = "ghost.jsonl"
    
    # File not found
    handle_replay(args)
        
    # Read error
    real_file = tmp_path / "read_err.jsonl"
    real_file.write_text("{}", encoding="utf-8")
    args.path = str(real_file)
    with patch("eval_runner.cli.load_events", side_effect=Exception("Read fail")):
        handle_replay(args)

# --- run_scenario extensions (641, 645-646) ---
@pytest.mark.asyncio
async def test_run_scenario_extensions(tmp_path, monkeypatch):
    from eval_runner.cli import run_scenario
    monkeypatch.chdir(tmp_path)
    args = MagicMock()
    args.scenario = "ghost.json"
    
    # File not found
    await run_scenario(args)
        
    # URL Benchmark
    args.scenario = "hf://test"
    with patch("eval_runner.loader.load_scenario", return_value=[{"scenario_id": "multi"}]), \
         patch("eval_runner.engine.run_evaluation", new_callable=MagicMock) as mock_eval:
        async def dummy(*a, **kw): pass
        mock_eval.side_effect = dummy
        await run_scenario(args)

# --- run_evaluate attempts and config (710-777) ---
@pytest.mark.asyncio
async def test_run_evaluate_complex_branches(mock_args, tmp_path, monkeypatch):
    from eval_runner.cli import run_evaluate
    monkeypatch.chdir(tmp_path)
    mock_args.path = "dummy.jsonl"
    mock_args.run_log_dir = "logs"
    mock_args.per_run_logs = True
    mock_args.master_log = True
    mock_args.seed = 42
    mock_args.protocol = "socket"
    mock_args.agent_socket = "unix:/path"
    mock_args.limit = 1
    mock_args.attempts = 2
    
    (tmp_path / "dummy.jsonl").write_text("{}", encoding="utf-8")
    
    mock_open = MagicMock()
    with patch("eval_runner.loader.load_dataset", return_value=[{"scenario_id": "s1"}]), \
         patch("eval_runner.engine.run_evaluation", new_callable=MagicMock) as mock_eval, \
         patch("eval_runner.metrics.calculate_consensus_scoring", return_value=1.0), \
         patch("builtins.open", mock_open):
         
        async def dummy(*a, **kw): 
            return [{"metrics": [{"success": True}], "conversation_history": [{"role": "agent", "content": {"summary": "done"}}]}]
        mock_eval.side_effect = dummy
        
        await run_evaluate(mock_args)

# --- aes validation missing (553-588) ---
def test_handle_aes_validate_complex(tmp_path, monkeypatch):
    from eval_runner.cli import handle_aes_validate
    monkeypatch.chdir(tmp_path)
    args = MagicMock()
    args.path = "test"
    
    # Schema not found
    handle_aes_validate(args)
        
    # Dir containing valid/invalid files
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    (test_dir / "valid.aes.yaml").write_text("{}", encoding="utf-8")
    
    with patch("json.loads", return_value={}), \
         patch("yaml.safe_load", return_value={}):
         
         # 1. Validation error branch
         with patch("jsonschema.validate", side_effect=Exception("ValidationError")):
              handle_aes_validate(args)
         
         # 2. Success branch
         with patch("jsonschema.validate"):
              handle_aes_validate(args)
