"""
test_cli_commands_extra.py

Unit tests for CLI handlers and complex branches (report, replay, run, evaluate, aes).
Refactored to eliminate "Mock Namespaces" and use real argparse objects.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import cli


def parse_args(cmd_list):
    """Helper to get a real argparse Namespace for a command."""
    parser = cli.get_parser(is_help=True)
    return parser.parse_args(cmd_list)


# --- handle_report exceptions ---
@pytest.mark.asyncio
async def test_handle_report_exceptions(tmp_path, monkeypatch):
    from eval_runner.handlers.analysis import handle_report

    monkeypatch.chdir(tmp_path)

    # File not found
    args = parse_args(["report", "--run-id", "ghost"])
    try:
        await handle_report(args)
    except Exception:
        pass

    # Read error
    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")

    args = parse_args(["report", "--run-id", "real"])
    with patch(
        "eval_runner.handlers.analysis.trace_utils.load_events", side_effect=Exception("Read fail")
    ):
        try:
            await handle_report(args)
        except Exception:
            pass


# --- handle_replay exceptions ---
@pytest.mark.asyncio
async def test_handle_replay_exceptions(tmp_path, monkeypatch):
    from eval_runner.handlers.evaluation import handle_replay

    monkeypatch.chdir(tmp_path)

    # File not found
    args = parse_args(["replay", "--run-id", "ghost"])
    with patch("eval_runner.config.RUN_LOG_DIR", tmp_path):
        with pytest.raises(SystemExit) as e:
            await handle_replay(args)
    assert e.value.code == 1

    # Read error
    real_file = tmp_path / "read_err.jsonl"
    real_file.write_text("{}", encoding="utf-8")

    args = parse_args(["replay", "--run-id", "read_err"])
    with (
        patch("eval_runner.config.RUN_LOG_DIR", tmp_path),
        patch(
            "eval_runner.handlers.analysis.trace_utils.load_events",
            side_effect=Exception("Read fail"),
        ),
    ):
        try:
            await handle_replay(args)
        except Exception:
            pass


# --- handle_run extensions ---
@pytest.mark.asyncio
async def test_handle_run_extensions(tmp_path, monkeypatch):
    from eval_runner.handlers.evaluation import handle_run as handle_run

    monkeypatch.chdir(tmp_path)

    # File not found
    args = parse_args(["run", "--scenario", "ghost.json"])
    with pytest.raises(SystemExit) as e:
        await handle_run(args)
    assert e.value.code == 1

    # URL Benchmark
    args = parse_args(["run", "--scenario", "hf://test"])
    with (
        patch("eval_runner.loader.load_scenario", return_value=[{"scenario_id": "multi"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_eval,
    ):
        mock_eval.return_value = []
        with pytest.raises(SystemExit) as e:
            await handle_run(args)
        assert e.value.code == 0


# --- run_evaluate attempts and config ---
@pytest.mark.asyncio
async def test_run_evaluate_complex_branches(tmp_path, monkeypatch):
    from eval_runner.handlers.evaluation import handle_evaluate as run_evaluate

    monkeypatch.chdir(tmp_path)

    log_dir = tmp_path / "logs"
    (tmp_path / "dummy.jsonl").write_text("{}", encoding="utf-8")

    args = parse_args(
        [
            "evaluate",
            "--path",
            "dummy.jsonl",
            "--run-log-dir",
            str(log_dir),
            "--per-run-logs",
            "--master-log",
            "--seed",
            "42",
            "--protocol",
            "socket",
            "--agent-socket",
            "unix:/path",
            "--limit",
            "1",
            "--attempts",
            "2",
        ]
    )

    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"scenario_id": "s1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_eval,
        patch("eval_runner.metrics.calculate_consensus_scoring", return_value=1.0),
        patch("builtins.open", MagicMock()),
    ):
        mock_eval.return_value = [
            {
                "metrics": [{"success": True}],
                "conversation_history": [{"role": "agent", "content": "done"}],
            }
        ]
        with pytest.raises(SystemExit) as e:
            await run_evaluate(args)
        assert e.value.code == 0


# --- aes validation missing ---
@pytest.mark.asyncio
async def test_handle_aes_validate_complex(tmp_path, monkeypatch):
    from eval_runner.handlers.scenarios import handle_aes_validate

    monkeypatch.chdir(tmp_path)

    # Dir containing valid/invalid files
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    (test_dir / "valid.aes.yaml").write_text("{}", encoding="utf-8")

    args = parse_args(["aes", "validate", "--path", str(test_dir)])

    with patch("json.loads", return_value={}), patch("yaml.safe_load", return_value={}):
        # 1. Validation error branch
        with patch("jsonschema.validate", side_effect=Exception("ValidationError")):
            await handle_aes_validate(args)

        # 2. Success branch
        with patch("jsonschema.validate"):
            await handle_aes_validate(args)
