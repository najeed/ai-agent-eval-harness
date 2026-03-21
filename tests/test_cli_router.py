import pytest
import sys
from unittest.mock import patch, MagicMock
from eval_runner import cli

# Test simple synchronous or asynchronous command routes by patching the ultimate handler.
@pytest.mark.parametrize("args, mock_target", [
    (["eval-harness", "init"], "eval_runner.cli.handle_init"),
    (["eval-harness", "import-drift", "--input", "x", "--industry", "x"], "eval_runner.cli.handle_import_drift"),
    (["eval-harness", "auto-translate", "--input", "x"], "eval_runner.cli.handle_auto_translate"),
    (["eval-harness", "replay"], "eval_runner.cli.handle_replay"),
    (["eval-harness", "mutate", "--input", "x", "--type", "typo"], "eval_runner.cli.handle_mutate"),
    (["eval-harness", "doctor"], "eval_runner.cli.handle_doctor"),
    (["eval-harness", "inspect", "--scenario-path", "x"], "eval_runner.cli.handle_inspect"),
    (["eval-harness", "taxonomy"], "eval_runner.cli.handle_taxonomy"),
    (["eval-harness", "catalog-search", "--query", "x"], "eval_runner.cli.handle_catalog_search"),
    (["eval-harness", "export", "--input", "i", "--output", "o"], "eval_runner.cli.handle_export"),
])
def test_router_sync_handlers(args, mock_target):
    with patch("sys.argv", args):
        with patch(mock_target) as mock_handler:
            # For async commands, we need to mock asyncio.run from cli context
            with patch("eval_runner.cli.asyncio.run") as mock_run:
                cli.main()
                # If it's async (auto-translate), it triggers asyncio.run(mock_target())
                # If sync, it triggers mock_target() directly
                # Parameterize handles both gracefully if we assert either was called
                if mock_run.called:
                    assert mock_run.call_count == 1
                else:
                    mock_handler.assert_called_once()

# Test commands that call specific modules

def test_router_console():
    with patch("sys.argv", ["eval-harness", "console"]), \
         patch("eval_runner.console.app.run_server") as mock_server:
        cli.main()
        mock_server.assert_called_once()

def test_router_quickstart():
    with patch("sys.argv", ["eval-harness", "quickstart"]), \
         patch("eval_runner.cli.asyncio.run") as mock_run:
        cli.main()
        mock_run.assert_called_once()

def test_router_scenario_generate():
    with patch("sys.argv", ["eval-harness", "scenario", "generate"]), \
         patch("eval_runner.scaffold.generate_interactive") as mock_gen:
        cli.main()
        mock_gen.assert_called_once()

def test_router_record():
    with patch("sys.argv", ["eval-harness", "record"]), \
         patch("eval_runner.cli.asyncio.run") as mock_run:
        cli.main()
        mock_run.assert_called_once()

def test_router_playground():
    with patch("sys.argv", ["eval-harness", "playground"]), \
         patch("eval_runner.cli.asyncio.run") as mock_run:
        cli.main()
        mock_run.assert_called_once()

def test_router_exception_exit():
    # Force an exception inside main to hit the traceback and sys.exit(1) block
    with patch("sys.argv", ["eval-harness", "list"]), \
         patch("eval_runner.cli.handle_list", side_effect=Exception("Crash")), \
         patch("traceback.print_exc") as mock_exc:
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 1
        mock_exc.assert_called_once()
