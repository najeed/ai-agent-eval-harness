from unittest.mock import AsyncMock, patch

import pytest

from eval_runner import cli


# Test simple synchronous or asynchronous command routes by patching the ultimate handler.
# Forensic Alignment: Handlers have moved from eval_runner.cli to eval_runner.handlers.*
@pytest.mark.parametrize(
    "args, mock_target",
    [
        (["agentv", "init"], "eval_runner.handlers.environment.handle_init"),
        (
            ["agentv", "import-drift", "--input", "x", "--industry", "x"],
            "eval_runner.handlers.scenarios.handle_import_drift",
        ),
        (
            ["agentv", "auto-translate", "--input", "x"],
            "eval_runner.handlers.environment.handle_auto_translate",
        ),
        (
            ["agentv", "replay", "--run-id", "test"],
            "eval_runner.handlers.evaluation.handle_replay",
        ),
        (
            ["agentv", "mutate", "--input", "x", "--type", "typo"],
            "eval_runner.handlers.scenarios.handle_mutate",
        ),
        (["agentv", "doctor"], "eval_runner.handlers.environment.handle_doctor"),
        (
            ["agentv", "inspect", "--scenario-path", "x"],
            "eval_runner.handlers.scenarios.handle_inspect",
        ),
        (["agentv", "taxonomy"], "eval_runner.handlers.analysis.handle_taxonomy"),
        (
            ["agentv", "catalog-search", "--query", "x"],
            "eval_runner.handlers.scenarios.handle_catalog_search",
        ),
        (
            ["agentv", "export", "--input", "i", "--output", "o"],
            "eval_runner.handlers.environment.handle_export",
        ),
        (
            ["agentv", "ci", "generate"],
            "eval_runner.handlers.environment.handle_ci_generate",
        ),
        (
            ["agentv", "install", "pack-name"],
            "eval_runner.handlers.environment.handle_install",
        ),
    ],
)
def test_router_sync_handlers(args, mock_target):
    with patch("sys.argv", args):
        with patch(mock_target, new_callable=AsyncMock, return_value=0) as mock_handler:
            with pytest.raises(SystemExit) as e:
                cli.main()
            assert e.value.code == 0
            mock_handler.assert_called_once()


# Test commands that call specific modules


def test_router_console():
    with (
        patch("sys.argv", ["agentv", "console"]),
        patch("eval_runner.console.app.run_server") as mock_server,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        mock_server.assert_called_once()


def test_router_quickstart():
    with (
        patch("sys.argv", ["agentv", "quickstart"]),
        patch(
            "eval_runner.handlers.evaluation.handle_quickstart",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_qs,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        mock_qs.assert_called_once()


def test_router_scenario_generate():
    with (
        patch("sys.argv", ["agentv", "scenario", "generate"]),
        patch("eval_runner.scaffold.generate_interactive") as mock_gen,
    ):
        mock_gen.return_value = 0
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        mock_gen.assert_called_once()


def test_router_record():
    with (
        patch("sys.argv", ["agentv", "record"]),
        patch(
            "eval_runner.handlers.evaluation.handle_record", new_callable=AsyncMock, return_value=0
        ) as mock_rec,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        mock_rec.assert_called_once()


def test_router_playground():
    with (
        patch("sys.argv", ["agentv", "playground"]),
        patch(
            "eval_runner.handlers.evaluation.handle_playground",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_pg,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        mock_pg.assert_called_once()


def test_router_exception_exit():
    # Forensic Alignment: Point to handlers.scenarios.handle_list
    with (
        patch("sys.argv", ["agentv", "list"]),
        patch("eval_runner.handlers.scenarios.handle_list", side_effect=Exception("Crash")),
        patch("traceback.print_exc") as mock_exc,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 1
        mock_exc.assert_called_once()
