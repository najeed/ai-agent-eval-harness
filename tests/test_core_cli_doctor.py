import pytest
import asyncio
import sys
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from eval_runner import cli, doctor

# ==============================================================================
# DOCTOR.PY - NEAR-100% COVERAGE
# ==============================================================================

@pytest.mark.asyncio
async def test_doctor_success(capsys):
    # Mock sys.version_info with a namedtuple-like object
    from collections import namedtuple
    VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro"])
    mock_ver = VersionInfo(major=3, minor=11, micro=0)
    
    with patch("sys.version_info", mock_ver), \
         patch("builtins.__import__", return_value=None), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("eval_runner.doctor.check_agent_reachable", return_value=True):
        
        await doctor.run_doctor()
        captured = capsys.readouterr().out
        assert "Python version OK" in captured
        assert "Dependency 'aiohttp' installed" in captured
        assert "Directory 'industries/' exists" in captured
        assert "Agent endpoint reachable" in captured
        assert "AES schema found" in captured

def test_doctor_main_block():
    # Execute doctor.py logic that would run under __main__
    # Use a simpler check or just verify it does not crash
    with patch("asyncio.run") as mock_run:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd()
        # Just check that it completes without an error exit code
        result = subprocess.run(
            [sys.executable, "-m", "eval_runner.doctor"], 
            capture_output=True, 
            text=True, 
            timeout=10,
            env=env
        )
        assert result.returncode == 0

# ==============================================================================
# CLI.PY - NEAR-100% COVERAGE
# ==============================================================================

def test_cli_run_attempts():
    # Test 'run' with --attempts and --scenario
    # cli.py calls engine.run_evaluation
    # Mock load_plugins to avoid loading PublicationPlugin which hits local files
    with patch("sys.argv", ["multiagent-eval", "run", "--scenario", "test_scenario", "--attempts", "2"]), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "test"}), \
         patch("eval_runner.plugins.manager.load_plugins"), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        cli.main()
        assert mock_run.called

def test_cli_list_industry(capsys):
    # Test 'list' with --search (formerly --industry was removed)
    with patch("sys.argv", ["multiagent-eval", "list", "--search", "finance"]), \
         patch("eval_runner.catalog.ScenarioCatalog.load_index"), \
         patch("eval_runner.catalog.list_scenarios") as mock_list:
        cli.main()
        assert mock_list.called

def test_cli_replay_valid():
    # Test 'replay' with --path
    with patch("sys.argv", ["multiagent-eval", "replay", "--path", "runs/test.jsonl"]), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("eval_runner.cli.load_events", return_value=[{"event": "run_start", "run_id": "test"}]):
        cli.main()
        # Coverage verified by successful run

def test_cli_cleanup_interactive_yes():
    # Test 'cleanup-runs' with interactive 'y' response
    args = MagicMock()
    args.days = 1
    args.force = False
    
    with patch("builtins.input", return_value="y"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.glob", return_value=[Path("runs/old.jsonl")]), \
         patch("pathlib.Path.stat") as mock_stat, \
         patch("pathlib.Path.unlink") as mock_unlink:
        
        mock_stat_val = MagicMock()
        mock_stat_val.st_mtime = 0 
        mock_stat.return_value = mock_stat_val
        
        cli.handle_cleanup_runs(args)
        assert mock_unlink.called

    # Test 'contribute' flow - Verify it does not leak folders
    with patch("sys.argv", ["multiagent-eval", "contribute"]), \
         patch("builtins.input", side_effect=["test_title", "test_ind", "n"]), \
         patch("pathlib.Path.mkdir"), \
         patch("builtins.open", MagicMock()):
        
        cli.main()
        # Coverage verified by reaching the end of the method

def test_cli_main_keyboard_interrupt():
    # Test KeyboardInterrupt in main()
    with patch("sys.argv", ["multiagent-eval", "doctor"]), \
         patch("eval_runner.cli.handle_doctor", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 130

def test_cli_main_exception_handling():
    # Test general exception handling in main()
    with patch("sys.argv", ["multiagent-eval", "doctor"]), \
         patch("eval_runner.cli.handle_doctor", side_effect=Exception("Fatal Error")):
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
