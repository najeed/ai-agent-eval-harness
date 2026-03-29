# tests/test_cli_handlers_coverage.py
import pytest
import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner import cli
from eval_runner.handlers import environment, scenarios, analysis, evaluation

@pytest.fixture
def mock_argv():
    with patch("sys.argv", ["multiagent-eval"]):
        yield sys.argv

def test_cli_version(capsys):
    """Test --version flag."""
    with patch("sys.argv", ["multiagent-eval", "--version"]):
        with pytest.raises(SystemExit) as e:
                cli.main()
        captured = capsys.readouterr()
        assert "MultiAgentEval" in captured.out

def test_cli_plugin_registration(capsys):
    """Test plugin command registration and execution."""
    from eval_runner.plugins import manager, BaseEvalPlugin
    
    class MockPlugin(BaseEvalPlugin):
        def on_register_commands(self, registry):
            # register_command calls add_parser and sets handler
            registry.register_command("mock-cmd", lambda args: print("Mock Plugin Command Run"), "help text")

    # Manually load into manager
    plugin_inst = MockPlugin()
    with patch.object(manager, "plugins", [plugin_inst]):
        # We need to trigger get_parser with 'plugin' in argv or help
        with patch("sys.argv", ["multiagent-eval", "plugin", "mock", "mock-cmd"]):
            try:
                cli.main()
            except SystemExit:
                pass
            captured = capsys.readouterr()
            pass

def test_handle_list_refresh(capsys):
    """Test 'list --refresh'."""
    with patch("eval_runner.handlers.scenarios.catalog.ScenarioCatalog.build_index") as mock_build:
        with patch("eval_runner.handlers.scenarios.catalog.list_scenarios"):
            args = MagicMock(refresh=True, search=None)
            scenarios.handle_list(args)
            mock_build.assert_called_once()

def test_handle_inspect_missing(capsys):
    """Test 'inspect' with missing file."""
    args = MagicMock(scenario_path="non_existent.json")
    scenarios.handle_inspect(args)
    captured = capsys.readouterr()
    assert "[ERROR] Scenario file not found" in captured.out

def test_handle_report_missing_trace(capsys):
    """Test 'report' with missing trace file."""
    args = MagicMock(path="missing.jsonl", share=False)
    analysis.handle_report(args)
    captured = capsys.readouterr()
    assert "[ERROR] Trace file not found" in captured.out

def test_handle_mutate_all_types(tmp_path, monkeypatch):
    """Test 'mutate' with various types to hit choice branches."""
    monkeypatch.chdir(tmp_path)
    input_file = Path("input.json")
    input_file.write_text(json.dumps({
        "description": "test", 
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task"}],
            "edges": []
        }
    }))
    output_file = Path("output.json")
    
    for mtype in ["typo", "injection", "ambiguity"]:
        # Use relative paths in argv
        with patch("sys.argv", ["multiagent-eval", "mutate", "--input", "input.json", "--type", mtype, "--output", "output.json"]):
                cli.main()


def test_handle_cleanup_runs(tmp_path, monkeypatch):
    """Test 'cleanup-runs' with force using mocking."""
    monkeypatch.chdir(tmp_path)
    old_file = Path("old.jsonl")
    old_file.write_text("old")
    
    # Mock time and Path methods to be platform-agnostic
    mock_stat = MagicMock()
    mock_stat.st_mtime = 0 # 1970
    
    with patch("time.time", return_value=1700000000), \
         patch("pathlib.Path.glob", return_value=[old_file]), \
         patch("pathlib.Path.stat", return_value=mock_stat), \
         patch("pathlib.Path.unlink") as mock_unlink:
        
        args = MagicMock(dir=".", days=7, force=True)
        environment.handle_cleanup_runs(args)
        # Verify unlink was called (file was deleted)
        mock_unlink.assert_called_once()

def test_handle_aes_validate_error_paths(tmp_path, capsys):
    """Test 'aes validate' with invalid files."""
    # 1. File not found
    args = MagicMock(path="non_existent_aes.yaml")
    scenarios.handle_aes_validate(args)
    captured = capsys.readouterr()
    assert "[ERROR] AES file not found" in captured.out

    # 2. Passing a directory (fails with Permission denied on read_text)
    args = MagicMock(path=str(tmp_path))
    scenarios.handle_aes_validate(args)
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.out

def test_handle_verify_missing(capsys):
    """Test 'verify' with missing file."""
    args = MagicMock(path="missing.jsonl", manifest=None)
    evaluation.handle_verify(args)
    captured = capsys.readouterr()
    assert "[ERROR] Trace file not found" in captured.out

def test_main_keyboard_interrupt():
    """Test KeyboardInterrupt handling in main()."""
    with patch("eval_runner.cli.get_parser", side_effect=KeyboardInterrupt):
        with patch("sys.argv", ["multiagent-eval", "list"]):
            with pytest.raises(SystemExit) as e:
                    cli.main()
            assert e.value.code == 130

def test_main_generic_exception():
    """Test generic Exception handling in main()."""
    with patch("eval_runner.cli.get_parser", side_effect=Exception("Unexpected")):
        with patch("sys.argv", ["multiagent-eval", "list"]):
            with pytest.raises(SystemExit) as e:
                cli.main()
            assert e.value.code == 1
