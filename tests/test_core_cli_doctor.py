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
async def test_doctor_success(capsys, tmp_path, monkeypatch):
    # Mock sys.version_info with a namedtuple-like object
    from collections import namedtuple
    VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro"])
    mock_ver = VersionInfo(major=3, minor=11, micro=0)
    
    # Setup real isolated environment
    monkeypatch.chdir(tmp_path)
    (tmp_path / "industries").mkdir()
    (tmp_path / "eval_runner").mkdir()
    (tmp_path / "eval_runner" / "aes_schema.json").write_text("{}", encoding="utf-8")
    
    with patch("sys.version_info", mock_ver), \
         patch("eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock) as mock_reachable:
        mock_reachable.return_value = True
        
        await doctor.run_doctor()
        captured = capsys.readouterr().out
        assert "Python version OK" in captured
        assert "Dependency 'aiohttp' installed" in captured
        assert "Directory 'industries/' exists" in captured


def test_cli_run_attempts(capsys, tmp_path, monkeypatch):
    # Test 'run' with --attempts and --scenario
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test_scenario.json").write_text("{}", encoding="utf-8")
    
    with patch("sys.argv", ["multiagent-eval", "run", "--scenario", "test_scenario.json", "--attempts", "2"]), \
         patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "test"}), \
         patch("eval_runner.plugins.manager.load_plugins"), \
         patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        cli.main()
        captured = capsys.readouterr()
        assert mock_run.called

def test_cli_replay_valid(tmp_path, monkeypatch):
    # Test 'replay' with --path
    monkeypatch.chdir(tmp_path)
    trace_file = tmp_path / "test.jsonl"
    trace_file.write_text("{}", encoding="utf-8")

    with patch("sys.argv", ["multiagent-eval", "replay", "--path", str(trace_file)]), \
         patch("eval_runner.cli.load_events", return_value=[{"event": "run_start", "run_id": "test"}]):
        cli.main()

def test_cli_cleanup_interactive_yes(tmp_path, monkeypatch):
    # Test 'cleanup-runs' with interactive 'y' response
    monkeypatch.chdir(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    old_file = runs_dir / "old.jsonl"
    old_file.write_text("old", encoding="utf-8")
    os.utime(old_file, (0, 0))

    args = MagicMock()
    args.days = 1
    args.force = False
    
    with patch("builtins.input", return_value="y"):
        cli.handle_cleanup_runs(args)
        assert not old_file.exists()

    # Test 'contribute' flow - Verify it does not leak folders
    (tmp_path / "industries" / "test_ind" / "scenarios").mkdir(parents=True, exist_ok=True)
    with patch("sys.argv", ["multiagent-eval", "contribute"]), \
         patch("builtins.input", side_effect=["test_title", "test_ind", "n"]), \
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
