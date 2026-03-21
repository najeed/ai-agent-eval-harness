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
def test_handle_report_exceptions():
    from eval_runner.cli import handle_report
    args = MagicMock()
    args.path = "ghost.jsonl"
    
    # 513-514: File not found
    with patch("eval_runner.cli.Path.exists", return_value=False):
        handle_report(args)
        
    # 518-520: Read error
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", side_effect=Exception("Read fail")):
        handle_report(args)
        
    # 524-526: No run_start defaults
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", return_value=[]), \
         patch("eval_runner.cli.reporter.generate_html_report"):
        handle_report(args)

# --- handle_replay exceptions (596-597, 601-603) ---
def test_handle_replay_exceptions():
    from eval_runner.cli import handle_replay
    args = MagicMock()
    
    # File not found
    with patch("eval_runner.cli.Path.exists", return_value=False):
        handle_replay(args)
        
    # Read error
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", side_effect=Exception("Read fail")):
        handle_replay(args)
        
    # Full coverage
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", return_value=[
             {"event": "run_start", "run_id": "r1", "scenario": "s1"},
             {"event": "prompt", "role": "user", "content": "hi"},
             {"event": "agent_response", "step": 1, "content": "hello"},
             {"event": "tool_call", "tool": "calc", "arguments": "1+1"},
             {"event": "tool_result", "tool": "calc", "result": "2"},
             {"event": "evaluation", "metric": "acc", "value": 1.0},
             {"event": "run_end", "status": "win"},
         ]):
        handle_replay(args)

# --- run_scenario extensions (641, 645-646) ---
@pytest.mark.asyncio
async def test_run_scenario_extensions():
    from eval_runner.cli import run_scenario
    args = MagicMock()
    args.scenario = "ghost.json"
    
    # File not found
    with patch("eval_runner.cli.Path.exists", return_value=False):
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
async def test_run_evaluate_complex_branches(mock_args):
    from eval_runner.cli import run_evaluate
    mock_args.path = "dummy.jsonl"
    mock_args.run_log_dir = "logs"
    mock_args.per_run_logs = True
    mock_args.master_log = True
    mock_args.seed = 42
    mock_args.protocol = "socket"
    mock_args.agent_socket = "unix:/path"
    mock_args.limit = 1
    mock_args.attempts = 2  # Triggers the massive 735-777 block
    
    with patch("eval_runner.loader.load_dataset", return_value=[{"scenario_id": "s1"}]), \
         patch("eval_runner.engine.run_evaluation", new_callable=MagicMock) as mock_eval, \
         patch("eval_runner.metrics.calculate_consensus_scoring", return_value=1.0), \
         patch("builtins.open"):
         
        # Simulate metric outcomes to calculate pass@k consistency
        async def dummy(*a, **kw): 
            return [{"metrics": [{"success": True}], "conversation_history": [{"role": "agent", "content": {"summary": "done"}}]}]
        mock_eval.side_effect = dummy
        
        await run_evaluate(mock_args)
        assert os.environ.get("RUN_LOG_DIR") == "logs"

# --- aes validation missing (553-588) ---
def test_handle_aes_validate_complex():
    from eval_runner.cli import handle_aes_validate
    args = MagicMock()
    args.path = "test"
    
    # Schema not found
    with patch("eval_runner.cli.Path.exists", return_value=False):
        handle_aes_validate(args)
        
    # Dir containing valid/invalid files
    with patch("eval_runner.cli.Path.exists", return_value=True), \
         patch("builtins.open") as mock_open, \
         patch("json.loads", return_value={}), \
         patch("eval_runner.cli.Path.is_dir", return_value=True), \
         patch("eval_runner.cli.Path.glob", side_effect=[[MagicMock(name="f1")], []]), \
         patch("yaml.safe_load", return_value={}):
         
         # 1. Validation error branch
         with patch("jsonschema.validate", side_effect=Exception("ValidationError")) as mock_val:
             # Need to mock jsonschema.exceptions.ValidationError properly, let's just trigger generic exception
             handle_aes_validate(args)
         
         # 2. Success branch
         with patch("jsonschema.validate"):
             handle_aes_validate(args)
