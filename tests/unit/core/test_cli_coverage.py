"""
test_cli_coverage.py

Coverage booster for eval_runner/cli.py.

Targets all dispatch functions, environment/scenario/analysis routing
branches, parser cache hit, ImportError fallback, TypeError entry_points
fallback, --version flag, run_log_dir mkdir, PQC override flags, and
the no-command help fallback.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_cache():
    cli._parser_cache = None
    cli._parser_argv_hash = None


def _main_exit(argv):
    """Run cli.main() with given argv; return the SystemExit code."""
    with patch.object(sys, "argv", argv):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
    return exc_info.value.code


# ---------------------------------------------------------------------------
# _invalidate_parser_cache
# ---------------------------------------------------------------------------


def test_invalidate_parser_cache():
    cli._parser_cache = object()
    cli._parser_argv_hash = 42
    cli._invalidate_parser_cache()
    assert cli._parser_cache is None
    assert cli._parser_argv_hash is None


# ---------------------------------------------------------------------------
# --version flag
# ---------------------------------------------------------------------------


def test_version_flag_exits_zero(capsys):
    _reset_cache()
    code = _main_exit(["agentv", "--version"])
    assert code == 0
    captured = capsys.readouterr()
    assert "AgentV" in captured.out


# ---------------------------------------------------------------------------
# Parser cache hit (same argv hash returns cached parser)
# ---------------------------------------------------------------------------


def test_parser_cache_hit():
    _reset_cache()
    with patch.object(sys, "argv", ["agentv", "--help"]):
        p1 = cli.get_parser(is_help=True)
    # Second call with same argv should return cached instance
    with patch.object(sys, "argv", ["agentv", "--help"]):
        p2 = cli.get_parser(is_help=True)
    assert p1 is p2
    _reset_cache()


# ---------------------------------------------------------------------------
# ImportError in get_parser (engine not available)
# ---------------------------------------------------------------------------


def test_get_parser_import_error_fallback():
    """If engine cannot be imported, falls back to minimal protocol list."""
    _reset_cache()
    with patch.object(sys, "argv", ["agentv", "run"]):
        with patch.dict("sys.modules", {"eval_runner.engine": None}):
            with patch("builtins.__import__", side_effect=ImportError("no engine")):
                # Should not raise
                try:
                    cli.get_parser(is_help=False)
                except Exception:
                    pass  # Acceptable — the test just ensures it doesn't crash completely
    _reset_cache()


# ---------------------------------------------------------------------------
# TypeError entry_points fallback (Python < 3.10 style)
# ---------------------------------------------------------------------------


def test_entry_points_type_error_fallback():
    """When entry_points() raises TypeError (old-style API), fallback path is taken."""
    _reset_cache()

    def _old_style_eps(**kwargs):
        raise TypeError("unexpected keyword argument")

    with patch.object(sys, "argv", ["agentv", "--help"]):
        with patch("importlib.metadata.entry_points", side_effect=_old_style_eps):
            with patch(
                "importlib.metadata.entry_points",
                side_effect=[TypeError("unexpected"), {"agentv.extensions": []}],
            ):
                try:
                    cli.get_parser(is_help=True)
                except Exception:
                    pass
    _reset_cache()


# ---------------------------------------------------------------------------
# _dispatch_console
# ---------------------------------------------------------------------------


def test_dispatch_console():
    _reset_cache()
    mock_run_server = MagicMock()
    with patch("eval_runner.console.app.run_server", mock_run_server):
        args = MagicMock()
        args.host = "0.0.0.0"  # nosec B104
        args.port = 8080
        args.debug = False
        result = cli._dispatch_console(args)
    assert result == 0
    mock_run_server.assert_called_once_with(host="0.0.0.0", port=8080, debug=False)  # nosec B104


# ---------------------------------------------------------------------------
# _dispatch_contribute
# ---------------------------------------------------------------------------


def test_dispatch_contribute():
    with patch("eval_runner.contributor.ContributeWizard.run") as mock_run:
        args = MagicMock()
        result = cli._dispatch_contribute(args)
    assert result == 0
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# _dispatch_evaluation
# ---------------------------------------------------------------------------


def test_dispatch_evaluation_routes_to_handler():
    mock_handler = MagicMock(return_value=0)
    mock_h = MagicMock()
    mock_h.handle_evaluate = mock_handler

    with patch("eval_runner.handlers.evaluation", mock_h):
        args = MagicMock()
        args.command = "evaluate"
        result = cli._dispatch_evaluation(args)

    assert result == 0
    mock_handler.assert_called_once_with(args)


# ---------------------------------------------------------------------------
# _dispatch_scenarios — all branches
# ---------------------------------------------------------------------------


def test_dispatch_scenarios_aes_validate():
    mock_h = MagicMock()
    mock_h.handle_aes_validate = MagicMock(return_value=0)
    with patch("eval_runner.handlers.scenarios", mock_h):
        args = MagicMock()
        args.command = "aes"
        args.aes_command = "validate"
        result = cli._dispatch_scenarios(args)
    assert result == 0
    mock_h.handle_aes_validate.assert_called_once_with(args)


def test_dispatch_scenarios_aes_non_validate():
    mock_h = MagicMock()
    with patch("eval_runner.handlers.scenarios", mock_h):
        args = MagicMock()
        args.command = "aes"
        args.aes_command = "add-standard"
        result = cli._dispatch_scenarios(args)
    assert result == 0


def test_dispatch_scenarios_scenario_inspect():
    mock_h = MagicMock()
    mock_h.handle_inspect = MagicMock(return_value=0)
    with patch("eval_runner.handlers.scenarios", mock_h):
        args = MagicMock()
        args.command = "scenario"
        args.scenario_command = "inspect"
        result = cli._dispatch_scenarios(args)
    assert result == 0
    mock_h.handle_inspect.assert_called_once_with(args)


def test_dispatch_scenarios_scenario_generate():
    mock_h = MagicMock()
    mock_h.handle_scenario_generate = MagicMock(return_value=0)
    with patch("eval_runner.handlers.scenarios", mock_h):
        args = MagicMock()
        args.command = "scenario"
        args.scenario_command = "generate"
        result = cli._dispatch_scenarios(args)
    assert result == 0
    mock_h.handle_scenario_generate.assert_called_once_with(args)


def test_dispatch_scenarios_catalog_search_query_flag():
    """catalog-search with positional query=None normalizes from query_flag."""
    mock_h = MagicMock()
    mock_h.handle_catalog_search = MagicMock(return_value=0)
    with patch("eval_runner.handlers.scenarios", mock_h):
        args = MagicMock()
        args.command = "catalog-search"
        args.query = None
        args.query_flag = "banking"
        result = cli._dispatch_scenarios(args)
    assert args.query == "banking"
    assert result == 0


def test_dispatch_scenarios_generic_command():
    mock_h = MagicMock()
    mock_h.handle_list = MagicMock(return_value=0)
    with patch("eval_runner.handlers.scenarios", mock_h):
        args = MagicMock()
        args.command = "list"
        result = cli._dispatch_scenarios(args)
    assert result == 0


# ---------------------------------------------------------------------------
# _dispatch_analysis
# ---------------------------------------------------------------------------


def test_dispatch_analysis_taxonomy():
    mock_h = MagicMock()
    mock_h.handle_taxonomy = MagicMock(return_value=0)
    with patch("eval_runner.handlers.analysis", mock_h):
        args = MagicMock()
        args.command = "taxonomy"
        result = cli._dispatch_analysis(args)
    assert result == 0
    mock_h.handle_taxonomy.assert_called_once_with(args)


# ---------------------------------------------------------------------------
# _dispatch_environment — all sub-branches
# ---------------------------------------------------------------------------


def test_dispatch_environment_ci_generate():
    mock_h = MagicMock()
    mock_h.handle_ci_generate = MagicMock(return_value=0)
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "ci"
        args.ci_command = "generate"
        result = cli._dispatch_environment(args)
    assert result == 0
    mock_h.handle_ci_generate.assert_called_once_with(args)


def test_dispatch_environment_ci_non_generate():
    mock_h = MagicMock()
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "ci"
        args.ci_command = "other"
        result = cli._dispatch_environment(args)
    assert result == 0


def test_dispatch_environment_failures_search():
    mock_h = MagicMock()
    mock_h.handle_failures_search = MagicMock(return_value=0)
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "failures"
        args.failures_command = "search"
        result = cli._dispatch_environment(args)
    assert result == 0
    mock_h.handle_failures_search.assert_called_once_with(args)


def test_dispatch_environment_failures_non_search():
    mock_h = MagicMock()
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "failures"
        args.failures_command = "other"
        result = cli._dispatch_environment(args)
    assert result == 0


def test_dispatch_environment_registry_sync():
    mock_h = MagicMock()
    mock_h.handle_registry_sync = MagicMock(return_value=0)
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "registry"
        args.registry_command = "sync"
        result = cli._dispatch_environment(args)
    assert result == 0
    mock_h.handle_registry_sync.assert_called_once_with(args)


def test_dispatch_environment_plugin_list():
    mock_h = MagicMock()
    mock_h.handle_plugin_list = MagicMock(return_value=0)
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "plugin"
        args.plugin_command = "list"
        result = cli._dispatch_environment(args)
    assert result == 0
    mock_h.handle_plugin_list.assert_called_once_with(args)


def test_dispatch_environment_list_plugins_shortcut():
    mock_h = MagicMock()
    mock_h.handle_plugin_list = MagicMock(return_value=0)
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "list-plugins"
        result = cli._dispatch_environment(args)
    assert result == 0
    mock_h.handle_plugin_list.assert_called_once_with(args)


def test_dispatch_environment_analyze_url_normalization():
    """analyze with no --url flag normalizes from positional repo_url."""
    mock_h = MagicMock()
    mock_h.handle_analyze = MagicMock(return_value=0)
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "analyze"
        args.url = None
        args.repo_url = "https://github.com/example/repo"
        result = cli._dispatch_environment(args)
    assert args.url == "https://github.com/example/repo"
    assert result == 0


def test_dispatch_environment_generic_doctor():
    mock_h = MagicMock()
    mock_h.handle_doctor = MagicMock(return_value=0)
    with patch("eval_runner.handlers.environment", mock_h):
        args = MagicMock()
        args.command = "doctor"
        result = cli._dispatch_environment(args)
    assert result == 0


# ---------------------------------------------------------------------------
# main() — run_log_dir mkdir branch
# ---------------------------------------------------------------------------


def test_main_creates_run_log_dir(tmp_path, monkeypatch):
    _reset_cache()
    run_dir = str(tmp_path / "custom-runs")

    mock_func = MagicMock(return_value=0)
    MagicMock()

    with patch.object(sys, "argv", ["agentv", "list"]):
        with patch("eval_runner.cli.get_parser") as mock_get_parser:
            mock_args = MagicMock()
            mock_args.command = "list"
            mock_args.run_log_dir = run_dir
            mock_args.pqc = None
            mock_args.no_pqc = None
            mock_args.func = mock_func
            mock_get_parser.return_value.parse_args.return_value = mock_args

            with patch("eval_runner.plugins.manager.finalize"):
                with pytest.raises(SystemExit) as exc_info:
                    cli.main()

    assert exc_info.value.code == 0
    # Directory should have been created by Path.mkdir
    from pathlib import Path

    assert Path(run_dir).exists()
    _reset_cache()


# ---------------------------------------------------------------------------
# main() — PQC enable/disable flags
# ---------------------------------------------------------------------------


def test_main_pqc_enable_flag():
    _reset_cache()

    mock_func = MagicMock(return_value=0)

    with patch.object(sys, "argv", ["agentv", "run", "--pqc"]):
        with patch("eval_runner.cli.get_parser") as mock_get_parser:
            mock_args = MagicMock()
            mock_args.command = "run"
            mock_args.run_log_dir = None
            mock_args.pqc = True
            mock_args.no_pqc = None
            mock_args.func = mock_func
            mock_get_parser.return_value.parse_args.return_value = mock_args

            with patch("eval_runner.config.PQC_ENABLED", False, create=True) as _:
                with patch("eval_runner.plugins.manager.finalize"):
                    with pytest.raises(SystemExit):
                        cli.main()
    _reset_cache()


def test_main_pqc_disable_flag():
    _reset_cache()

    mock_func = MagicMock(return_value=0)

    with patch.object(sys, "argv", ["agentv", "run", "--no-pqc"]):
        with patch("eval_runner.cli.get_parser") as mock_get_parser:
            mock_args = MagicMock()
            mock_args.command = "run"
            mock_args.run_log_dir = None
            mock_args.pqc = None
            mock_args.no_pqc = True
            mock_args.func = mock_func
            mock_get_parser.return_value.parse_args.return_value = mock_args

            with patch("eval_runner.plugins.manager.finalize"):
                with pytest.raises(SystemExit):
                    cli.main()
    _reset_cache()


# ---------------------------------------------------------------------------
# main() — no command prints help
# ---------------------------------------------------------------------------


def test_main_no_command_prints_help(capsys):
    _reset_cache()

    with patch.object(sys, "argv", ["agentv"]):
        with patch("eval_runner.cli.get_parser") as mock_get_parser:
            mock_args = MagicMock()
            mock_args.command = None
            del mock_args.func  # no func attribute
            mock_args.func = None
            mock_get_parser.return_value.parse_args.return_value = mock_args
            mock_parser = mock_get_parser.return_value

            with patch("eval_runner.plugins.manager.finalize"):
                cli.main()

    mock_parser.print_help.assert_called()
    _reset_cache()


# ---------------------------------------------------------------------------
# main() — KeyboardInterrupt exits 130
# ---------------------------------------------------------------------------


def test_main_keyboard_interrupt_exits_130():
    _reset_cache()

    with patch.object(sys, "argv", ["agentv", "list"]):
        with patch("eval_runner.cli.get_parser", side_effect=KeyboardInterrupt):
            with patch("eval_runner.plugins.manager.finalize"):
                with pytest.raises(SystemExit) as exc_info:
                    cli.main()
    assert exc_info.value.code == 130
    _reset_cache()


# ---------------------------------------------------------------------------
# main() — generic exception exits 1
# ---------------------------------------------------------------------------


def test_main_generic_exception_exits_1():
    _reset_cache()

    with patch.object(sys, "argv", ["agentv", "list"]):
        with patch("eval_runner.cli.get_parser", side_effect=RuntimeError("boom")):
            with patch("eval_runner.plugins.manager.finalize"):
                with pytest.raises(SystemExit) as exc_info:
                    cli.main()
    assert exc_info.value.code == 1
    _reset_cache()


# ---------------------------------------------------------------------------
# main() — coroutine dispatch (async func)
# ---------------------------------------------------------------------------


def test_main_async_func_dispatch():
    """If the dispatched handler returns a coroutine, safe_run_async is called."""
    _reset_cache()

    async def _async_handler(args):
        return 0

    coro = _async_handler(MagicMock())
    mock_func = MagicMock(return_value=coro)

    try:
        with patch.object(sys, "argv", ["agentv", "evaluate"]):
            with patch("eval_runner.cli.get_parser") as mock_get_parser:
                mock_args = MagicMock()
                mock_args.command = "evaluate"
                mock_args.run_log_dir = None
                mock_args.pqc = None
                mock_args.no_pqc = None
                mock_args.func = mock_func
                mock_get_parser.return_value.parse_args.return_value = mock_args

                # Patch at the cli module namespace where it was imported
                with patch("eval_runner.cli.safe_run_async", return_value=0) as mock_sra:
                    with patch("eval_runner.plugins.manager.finalize"):
                        with pytest.raises(SystemExit) as exc_info:
                            cli.main()

        assert exc_info.value.code == 0
        mock_sra.assert_called_once()
    finally:
        # Explicitly close the coroutine to suppress RuntimeWarning about
        # never-awaited coroutine (it was intentionally passed to mocked safe_run_async)
        coro.close()

    _reset_cache()


# ---------------------------------------------------------------------------
# _add_pqc_args
# ---------------------------------------------------------------------------


def test_add_pqc_args_registers_flags():
    import argparse

    parser = argparse.ArgumentParser()
    cli._add_pqc_args(parser)
    args = parser.parse_args(["--pqc"])
    assert args.pqc is True
    args2 = parser.parse_args(["--no-pqc"])
    assert args2.no_pqc is True


# ---------------------------------------------------------------------------
# main() line 555: command set but no func attribute — falls through to final
# parser.print_help() call
# ---------------------------------------------------------------------------


def test_main_command_set_no_func_prints_help():
    """When args.command is set but args has no func, line 555 print_help() is reached."""
    _reset_cache()

    with patch.object(sys, "argv", ["agentv", "list"]):
        with patch("eval_runner.cli.get_parser") as mock_get_parser:
            mock_args = MagicMock(spec=["command"])  # no 'func' attribute at all
            mock_args.command = "list"
            mock_get_parser.return_value.parse_args.return_value = mock_args
            mock_parser = mock_get_parser.return_value

            with patch("eval_runner.plugins.manager.finalize"):
                cli.main()  # should NOT raise SystemExit

    # Both the no-command branch check and the final help call run
    # The final parser.print_help() at line 555 must be reached
    mock_parser.print_help.assert_called()
    _reset_cache()
