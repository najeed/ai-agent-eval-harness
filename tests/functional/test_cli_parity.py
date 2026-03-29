import eval_runner
import eval_runner.handlers.evaluation
import pytest
from unittest.mock import MagicMock, patch
from eval_runner import cli

def test_run_parser_parity():
    """Verifies 'run' parser now includes previously missing infrastructure arguments."""
    parser = cli.get_parser(is_help=True)
    
    # Check 'run' subparser
    subparsers = [action for action in parser._actions if isinstance(action, cli.argparse._SubParsersAction)][0]
    run_parser = subparsers.choices["run"]
    
    arg_names = [action.dest for action in run_parser._actions]
    assert "agent_name" in arg_names
    assert "verbose" in arg_names
    assert "output" in arg_names
    assert "run_log_dir" in arg_names

def test_record_playground_parity():
    """Verifies 'record' and 'playground' parsers include agent name and verbose flags."""
    parser = cli.get_parser(is_help=True)
    subparsers = [action for action in parser._actions if isinstance(action, cli.argparse._SubParsersAction)][0]
    
    for cmd in ["record", "playground"]:
        p = subparsers.choices[cmd]
        arg_names = [action.dest for action in p._actions]
        assert "agent_name" in arg_names
        assert "verbose" in arg_names

@patch("eval_runner.loader.load_scenario")
@patch("eval_runner.engine.run_evaluation")
def test_handle_run_env_propagation(mock_eval, mock_load, tmp_path):
    """Verifies run_scenario correctly sets environment variables like evaluate does."""
    mock_load.return_value = {"scenario_id": "test"}
    mock_eval.return_value = []
    
    args = MagicMock()
    args.scenario = "test.json"
    args.run_log_dir = str(tmp_path / "custom_runs")
    args.per_run_logs = True
    args.seed = 42
    args.attempts = 1
    
    import asyncio
    import os
    
    asyncio.run(eval_runner.handlers.evaluation.handle_run(args))
    
    assert os.environ.get("RUN_LOG_DIR") == str(tmp_path / "custom_runs")
    assert os.environ.get("RUN_LOG_PER_RUN") == "true"
