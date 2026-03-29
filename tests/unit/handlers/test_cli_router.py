import pytest
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner import cli

# Test simple synchronous or asynchronous command routes by patching the ultimate handler.
# Forensic Alignment: Handlers have moved from eval_runner.cli to eval_runner.handlers.*
@pytest.mark.parametrize("args, mock_target", [
    (["multiagent-eval", "init"], "eval_runner.handlers.environment.handle_init"),
    (["multiagent-eval", "import-drift", "--input", "x", "--industry", "x"], "eval_runner.handlers.scenarios.handle_import_drift"),
    (["multiagent-eval", "auto-translate", "--input", "x"], "eval_runner.handlers.environment.handle_auto_translate"),
    (["multiagent-eval", "replay"], "eval_runner.handlers.evaluation.handle_replay"),
    (["multiagent-eval", "mutate", "--input", "x", "--type", "typo"], "eval_runner.handlers.scenarios.handle_mutate"),
    (["multiagent-eval", "doctor"], "eval_runner.handlers.environment.handle_doctor"),
    (["multiagent-eval", "inspect", "--scenario-path", "x"], "eval_runner.handlers.scenarios.handle_inspect"),
    (["multiagent-eval", "taxonomy"], "eval_runner.handlers.analysis.handle_taxonomy"),
    (["multiagent-eval", "catalog-search", "--query", "x"], "eval_runner.handlers.scenarios.handle_catalog_search"),
    (["multiagent-eval", "export", "--input", "i", "--output", "o"], "eval_runner.handlers.environment.handle_export"),
    (["multiagent-eval", "ci", "generate"], "eval_runner.handlers.environment.handle_ci_generate"),
    (["multiagent-eval", "install", "pack-name"], "eval_runner.handlers.environment.handle_install"),
])
def test_router_sync_handlers(args, mock_target):
    with patch("sys.argv", args):
        with patch(mock_target) as mock_handler:
            # For async commands, we need to mock asyncio.run from cli context
            with patch("eval_runner.cli.asyncio.run") as mock_run:
                cli.main()
                # If it's async, it triggers asyncio.run(mock_target())
                # If sync, it triggers mock_target() directly
                if mock_run.called:
                    assert mock_run.call_count == 1
                else:
                    mock_handler.assert_called_once()

# Test commands that call specific modules

def test_router_console():
    with patch("sys.argv", ["multiagent-eval", "console"]), \
         patch("eval_runner.console.app.run_server") as mock_server:
        cli.main()
        mock_server.assert_called_once()

def test_router_quickstart():
    with patch("sys.argv", ["multiagent-eval", "quickstart"]), \
         patch("eval_runner.quickstart.run_quickstart") as mock_qs, \
         patch("eval_runner.cli.asyncio.run") as mock_run:
        cli.main()
        mock_run.assert_called_once()

def test_router_scenario_generate():
    with patch("sys.argv", ["multiagent-eval", "scenario", "generate"]), \
         patch("eval_runner.scaffold.generate_interactive") as mock_gen:
        cli.main()
        mock_gen.assert_called_once()

def test_router_record():
    with patch("sys.argv", ["multiagent-eval", "record"]), \
         patch("eval_runner.trace_recorder.record_interaction") as mock_rec, \
         patch("eval_runner.cli.asyncio.run") as mock_run:
        cli.main()
        mock_run.assert_called_once()

def test_router_playground():
    with patch("sys.argv", ["multiagent-eval", "playground"]), \
         patch("eval_runner.playground.run_playground") as mock_pg, \
         patch("eval_runner.cli.asyncio.run") as mock_run:
        cli.main()
        mock_run.assert_called_once()

def test_router_exception_exit():
    # Forensic Alignment: Point to handlers.scenarios.handle_list
    with patch("sys.argv", ["multiagent-eval", "list"]), \
         patch("eval_runner.handlers.scenarios.handle_list", side_effect=Exception("Crash")), \
         patch("traceback.print_exc") as mock_exc:
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 1
        mock_exc.assert_called_once()
