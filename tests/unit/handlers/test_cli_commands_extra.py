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
        result = await handle_replay(args)
    assert result == 1

    # Read error
    run_dir = tmp_path / "read_err"
    run_dir.mkdir()
    real_file = run_dir / "run.jsonl"
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
    result = await handle_run(args)
    assert result == 1

    # URL Benchmark
    args = parse_args(["run", "--scenario", "hf://test"])
    with (
        patch("eval_runner.loader.load_scenario", return_value=[{"id": "multi"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_eval,
    ):
        mock_eval.return_value = []
        result = await handle_run(args)
        assert result == 0


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
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1"}]),
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
        result = await run_evaluate(args)
        assert result == 0


# --- aes validation missing ---
@pytest.mark.asyncio
async def test_handle_aes_validate_real(tmp_path, monkeypatch):
    import json

    from eval_runner.handlers.scenarios import handle_aes_validate

    monkeypatch.chdir(tmp_path)

    # 1. Valid scenario
    valid_file = tmp_path / "valid.json"
    valid_file.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {
                    "name": "Valid Scenario",
                    "id": "valid_id",
                    "compliance_level": "Standard",
                },
                "workflow": {"nodes": [], "edges": []},
                "evaluation": {
                    "consensus": {
                        "strategy": "Majority_Vote",
                        "min_judges": 1,
                        "judge_panel": ["Luna-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    # 2. Invalid scenario (missing required workflow)
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {"name": "Invalid Scenario"},
            }
        ),
        encoding="utf-8",
    )

    # Test valid scenario validate
    args_valid = parse_args(["aes", "validate", "--path", str(valid_file)])
    res_valid = await handle_aes_validate(args_valid)
    assert res_valid == 0

    # Test invalid scenario validate
    args_invalid = parse_args(["aes", "validate", "--path", str(invalid_file)])
    res_invalid = await handle_aes_validate(args_invalid)
    assert res_invalid == 1


@pytest.mark.asyncio
async def test_handle_run_and_evaluate_trace_schema_validation(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from jsonschema import validate

    from eval_runner.handlers.evaluation import handle_run

    monkeypatch.chdir(tmp_path)

    # Setup custom log directory in tmp_path
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", log_dir)
    monkeypatch.setenv("RUN_LOG_DIR", str(log_dir))

    scenario_file = tmp_path / "test_scenario.json"
    scenario_file.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {
                    "name": "Run Schema Test",
                    "id": "run_schema_test",
                    "compliance_level": "Standard",
                },
                "workflow": {
                    "nodes": [
                        {
                            "id": "task-1",
                            "task_description": "Do something",
                            "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
                        }
                    ],
                    "edges": [],
                },
                "evaluation": {
                    "consensus": {
                        "strategy": "Majority_Vote",
                        "min_judges": 1,
                        "judge_panel": ["Luna-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    # Mock a minimal agent response for the local protocol
    async def mock_call_agent(*args, **kwargs):
        return {"action": "final_answer", "summary": "Successfully completed task"}

    args_run = parse_args(
        [
            "run",
            "--scenario",
            str(scenario_file),
            "--run-id",
            "test-run-schema-compliance",
            "--attempts",
            "1",
            "--run-log-dir",
            str(log_dir),
        ]
    )

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_call_agent):
        res = await handle_run(args_run)
        assert res == 0

    # Verify run.jsonl conforms to spec/runs/runs.schema.json
    trace_path = log_dir / "test-run-schema-compliance" / "run.jsonl"
    assert trace_path.exists()

    project_root = Path(__file__).parent.parent.parent.parent
    runs_schema_path = project_root / "spec" / "runs" / "runs.schema.json"
    assert runs_schema_path.exists()

    with open(runs_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    with open(trace_path, encoding="utf-8") as tf:
        for line in tf:
            if line.strip():
                event = json.loads(line)
                validate(instance=event, schema=schema)
