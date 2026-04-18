from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.cli import main


@pytest.fixture
def mock_sys_exit():
    with patch("sys.exit") as mock_exit:
        yield mock_exit


@pytest.fixture
def mock_handlers():
    with (
        patch("eval_runner.handlers.evaluation", autospec=True) as h_eval,
        patch("eval_runner.handlers.scenarios", autospec=True) as h_scen,
        patch("eval_runner.handlers.analysis", autospec=True) as h_anal,
        patch("eval_runner.handlers.environment", autospec=True) as h_env,
        patch("eval_runner.console.app.run_server", autospec=True) as h_cons,
        patch("eval_runner.contributor.ContributeWizard.run", autospec=True) as h_cont,
    ):
        # Set all handlers to return 0 or None (success)
        for h in [h_eval, h_scen, h_anal, h_env]:
            for attr in dir(h):
                if attr.startswith("handle_"):
                    # Use AsyncMock since safe_run_async is used
                    setattr(h, attr, AsyncMock(return_value=0))

        yield {
            "evaluation": h_eval,
            "scenarios": h_scen,
            "analysis": h_anal,
            "environment": h_env,
            "console": h_cons,
            "contribute": h_cont,
        }


@pytest.mark.parametrize(
    "args, handler_path, handler_func",
    [
        (["evaluate", "--path", "."], "evaluation", "handle_evaluate"),
        (["run", "--path", "."], "evaluation", "handle_run"),
        (["record", "--scenario", "s1"], "evaluation", "handle_record"),
        (["playground"], "evaluation", "handle_playground"),
        (["replay", "--run-id", "r1"], "evaluation", "handle_replay"),
        (["verify", "--path", "."], "evaluation", "handle_verify"),
        (["certify", "--path", "."], "evaluation", "handle_certify"),
        (["gate", "--path", "."], "evaluation", "handle_gate"),
        (["quickstart"], "evaluation", "handle_quickstart"),
        (["aes", "validate", "--path", "."], "scenarios", "handle_aes_validate"),
        (["inspect", "--path", "."], "scenarios", "handle_inspect"),
        (["lint", "--path", "."], "scenarios", "handle_lint"),
        (["list"], "scenarios", "handle_list"),
        (["catalog-search", "query"], "scenarios", "handle_catalog_search"),
        (["catalog-refresh"], "scenarios", "handle_catalog_refresh"),
        (["mutate", "--path", "."], "scenarios", "handle_mutate"),
        (["scenario", "generate"], "scenarios", "handle_scenario_generate"),
        (["scenario", "inspect", "--path", "."], "scenarios", "handle_inspect"),
        (["spec-to-eval", "--markdown", "# Test"], "scenarios", "handle_spec_to_eval"),
        (["import-drift", "--path", "."], "scenarios", "handle_import_drift"),
        (["calibrate"], "analysis", "handle_calibrate"),
        (["explain", "--run-id", "r1"], "analysis", "handle_explain"),
        (["leaderboard"], "analysis", "handle_leaderboard"),
        (["report", "--run-id", "all"], "analysis", "handle_report"),
        (["taxonomy"], "analysis", "handle_taxonomy"),
        (["list-metrics"], "analysis", "handle_list_metrics"),
        (["analyze", "--path", "."], "environment", "handle_analyze"),
        (["list-plugins"], "environment", "handle_plugin_list"),
        (["auto-translate", "--path", "."], "environment", "handle_auto_translate"),
        (["ci", "generate"], "environment", "handle_ci_generate"),
        (["cleanup-runs"], "environment", "handle_cleanup_runs"),
        (["doctor"], "environment", "handle_doctor"),
        (["export", "--run-id", "r1"], "environment", "handle_export"),
        (["failures", "search", "err"], "environment", "handle_failures_search"),
        (["init"], "environment", "handle_init"),
        (["install", "plugin-x"], "environment", "handle_install"),
        (["registry", "sync"], "environment", "handle_registry_sync"),
        (["registry", "add", "url"], "environment", "handle_registry_add"),
        (["registry", "search", "q"], "environment", "handle_registry_search"),
        (["plugin", "list"], "environment", "handle_plugin_list"),
        (["plugin", "register", "p1"], "environment", "handle_plugin_register"),
        (["plugin", "unregister", "p1"], "environment", "handle_plugin_unregister"),
    ],
)
def test_cli_routing(args, handler_path, handler_func, mock_handlers, mock_sys_exit):
    """Verify that each CLI command is routed to its respective handler function."""
    with patch("sys.argv", ["agentv"] + args):
        main()

        handler_module = mock_handlers[handler_path]
        handler_method = getattr(handler_module, handler_func)
        handler_method.assert_called_once()
        mock_sys_exit.assert_called()


def test_cli_routing_console(mock_handlers, mock_sys_exit, capsys):
    """Verify console command routing."""
    with patch("sys.argv", ["agentv", "console"]):
        main()
        mock_handlers["console"].assert_called_once()
        mock_sys_exit.assert_called_with(0)


def test_cli_routing_contribute(mock_handlers, mock_sys_exit):
    """Verify contribute command routing."""
    with patch("sys.argv", ["agentv", "contribute"]):
        main()
        mock_handlers["contribute"].assert_called_once()
        mock_sys_exit.assert_called_with(0)
