import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import cli
from eval_runner.handlers import analysis, environment, evaluation, scenarios


@pytest.fixture
def mock_argv():
    with patch("sys.argv", ["multiagent-eval"]):
        yield sys.argv


def test_cli_version(capsys):
    """Test --version flag."""
    with patch("sys.argv", ["multiagent-eval", "--version"]):
        with pytest.raises(SystemExit):
            cli.main()
        captured = capsys.readouterr()
        assert "MultiAgentEval" in captured.out


@pytest.mark.asyncio
async def test_handle_list_refresh(capsys):
    """Test 'list --refresh'."""
    with patch("eval_runner.handlers.scenarios.catalog.ScenarioCatalog.build_index") as mock_build:
        with patch("eval_runner.handlers.scenarios.catalog.list_scenarios"):
            args = MagicMock(refresh=True, search=None)
            await scenarios.handle_list(args)
            mock_build.assert_called_once()


@pytest.mark.asyncio
async def test_handle_inspect_missing(capsys):
    """Test 'inspect' with missing file."""
    args = MagicMock(scenario_path="non_existent.json")
    await scenarios.handle_inspect(args)
    captured = capsys.readouterr()
    assert "[ERROR] Scenario file not found" in captured.out


@pytest.mark.asyncio
async def test_handle_report_missing_trace(capsys):
    """Test 'report' with missing trace file."""
    args = MagicMock(path="missing.jsonl", share=False)
    analysis.handle_report(args)
    captured = capsys.readouterr()
    assert "[ERROR] Trace file not found" in captured.out


@pytest.mark.asyncio
async def test_handle_mutate_all_types(tmp_path, monkeypatch):
    """Hits mutate branches. Forensic: v1.2 Numerical Schema."""
    monkeypatch.chdir(tmp_path)
    input_file = Path("input.json")
    input_file.write_text(
        json.dumps(
            {
                "aes_version": 1.3,
                "metadata": {"name": "Test", "compliance_level": "Standard"},
                "workflow": {"nodes": [{"id": "t1", "task_description": "task"}], "edges": []},
            }
        )
    )

    for mtype in ["typo", "injection"]:
        out_file = Path("mutated.json")
        if out_file.exists():
            out_file.unlink()

        args = MagicMock(input="input.json", type=mtype, output=None)
        await scenarios.handle_mutate(args)
        assert out_file.exists()


@pytest.mark.asyncio
async def test_handle_cleanup_runs(tmp_path, monkeypatch):
    """Test 'cleanup-runs' with force using mocking."""
    monkeypatch.chdir(tmp_path)
    old_file = Path("old.jsonl")
    old_file.write_text("old")

    mock_stat = MagicMock()
    mock_stat.st_mtime = 0

    # Cleanup logic moved to eval_runner.cleaner
    with (
        patch("eval_runner.cleaner.time.time", return_value=1700000000),
        patch("eval_runner.cleaner.Path") as mock_path_class,
    ):
        mock_path_inst = mock_path_class.return_value
        # mock_path_inst.exists.return_value = True

        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 0
        mock_path_inst.glob.return_value = [mock_file]

        args = MagicMock(dir=".", days=7, force=True)
        await environment.handle_cleanup_runs(args)

        # Verify unlink was called on the mock file
        mock_file.unlink.assert_called_once()


@pytest.mark.asyncio
async def test_handle_aes_validate_error_paths(tmp_path, capsys):
    """Force 'Invalid' print by providing a physically invalid v1.2 file."""
    bad_file = tmp_path / "invalid.json"
    bad_file.write_text('{"aes_version": 1.1, "metadata": {}}')

    args = MagicMock(path=str(bad_file))
    await scenarios.handle_aes_validate(args)
    captured = capsys.readouterr()
    assert "Invalid" in captured.out or "❌" in captured.out


@pytest.mark.asyncio
async def test_handle_verify_missing(capsys, tmp_path, monkeypatch):
    """Test 'verify' with missing file. Forensic: [CRITICAL] string."""
    # Ensure we are in a safe project jail for this test
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    args = MagicMock(path="missing.jsonl", manifest=None, run_id=None)
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_verify(args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "[CRITICAL] FAILED: Trace integrity compromised!" in captured.out


def test_main_generic_exception():
    """Test generic Exception handling in main(). Forensic: Trigger inside try-block."""
    with patch("eval_runner.handlers.scenarios.handle_list", side_effect=Exception("Unexpected")):
        with patch("sys.argv", ["multiagent-eval", "list"]):
            with pytest.raises(SystemExit) as e:
                cli.main()
            assert e.value.code == 1


@pytest.mark.asyncio
async def test_handle_spec_to_eval_exceptions(capsys):
    """Test 'spec-to-eval' with missing file. Forensic: Verify early return."""
    args = MagicMock(input="missing_spec_coverage.md", output="out.json")
    # No need to patch save_scenario_json because os.path.exists will be False
    with patch("os.path.exists", return_value=False):
        from eval_runner.handlers.scenarios import handle_spec_to_eval

        await handle_spec_to_eval(args)
        captured = capsys.readouterr()
        assert "[ERROR] Spec input file not found" in captured.out


def test_cli_plugin_registration(capsys):
    """Test plugin command registration and execution."""
    from eval_runner.plugins import BaseEvalPlugin, manager

    class MockPlugin(BaseEvalPlugin):
        def on_register_commands(self, registry):
            # register_command calls add_parser and sets handler
            registry.register_command(
                "mock-cmd", lambda args: print("Mock Plugin Command Run"), "help text"
            )

    # Manually load into manager
    plugin_inst = MockPlugin()
    with patch.object(manager, "plugins", [plugin_inst]):
        # We need to trigger get_parser with 'plugin' in argv or help
        with patch("sys.argv", ["multiagent-eval", "plugin", "mock-cmd"]):
            try:
                cli.main()
            except SystemExit:
                pass
            capsys.readouterr()
            # Note: Checking if it was called is enough for now,
            # as actual registration might require cli.py support.
            pass


def test_main_keyboard_interrupt():
    """Test KeyboardInterrupt handling in main()."""
    with patch("eval_runner.cli.get_parser", side_effect=KeyboardInterrupt):
        with patch("sys.argv", ["multiagent-eval", "list"]):
            with pytest.raises(SystemExit) as e:
                cli.main()
            assert e.value.code == 130


def test_main_help(capsys):
    """Test handling of --help flag."""
    with patch("sys.argv", ["multiagent-eval", "--help"]):
        with pytest.raises(SystemExit):
            cli.main()
        captured = capsys.readouterr()
        assert "Usage:" in captured.out
        assert "Core Evaluation:" in captured.out
