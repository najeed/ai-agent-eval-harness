"""
test_cli_commands_more.py

Unit tests for specialized CLI commands (spec-to-eval, mutate, failures, explain, calibrate).
Refactored to eliminate "Mock Namespaces" and use real argparse objects.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import cli


def parse_args(cmd_list):
    """Helper to get a real argparse Namespace for a command."""
    parser = cli.get_parser(is_help=True)
    return parser.parse_args(cmd_list)


# --- handle_spec_to_eval ---
@pytest.mark.asyncio
async def test_handle_spec_to_eval_exceptions(tmp_path, monkeypatch):
    from eval_runner.handlers.scenarios import handle_spec_to_eval

    monkeypatch.chdir(tmp_path)

    # input missing (real parser will catch this or we handle it in code)
    args = parse_args(["spec-to-eval", "--input", "ghost.md"])
    await handle_spec_to_eval(args)

    # Valid md for parsing
    input_file = tmp_path / "real.md"
    input_file.write_text("# Demo", encoding="utf-8")

    args = parse_args(["spec-to-eval", "--input", str(input_file)])

    with (
        patch("builtins.open", MagicMock()),
        patch("eval_runner.spec_parser.parse_markdown_to_scenario", return_value={"title": "demo"}),
        patch(
            "eval_runner.handlers.scenarios.classify_scenario",
            return_value={"industry": "finance", "use_case": "Support", "core_function": "Help"},
        ),
        patch(
            "eval_runner.handlers.scenarios.spec_parser.save_scenario_json",
            side_effect=Exception("Conversion failed"),
        ),
    ):
        from eval_runner.handlers.scenarios import handle_spec_to_eval

        res = await handle_spec_to_eval(args)
        assert res == 1


@pytest.mark.asyncio
async def test_handle_spec_to_eval_success(tmp_path, monkeypatch):
    from pathlib import Path

    from jsonschema import validate
    from referencing import Registry, Resource

    from eval_runner.handlers.scenarios import handle_spec_to_eval

    monkeypatch.chdir(tmp_path)

    input_file = tmp_path / "real.md"
    input_file.write_text(
        "# Demo Scenario\n"
        "**Industry:** Fintech\n"
        "**Use Case:** Test\n"
        "**Core Function:** Check\n"
        "## Tasks\n"
        "### 1. Check\n"
        "Verify details",
        encoding="utf-8",
    )

    output_file = tmp_path / "output.json"
    args = parse_args(["spec-to-eval", "--input", str(input_file), "--output", str(output_file)])

    res = await handle_spec_to_eval(args)
    assert res == 0
    assert output_file.exists()

    with open(output_file, encoding="utf-8") as f:
        scenario = json.load(f)

    project_root = Path(__file__).parent.parent.parent.parent
    schema_path = project_root / "spec" / "aes" / "aes.schema.json"
    assert schema_path.exists()

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    defs_dir = schema_path.parent / "definitions"
    registry = Registry()
    if defs_dir.exists():
        for fpath in defs_dir.glob("*.json"):
            with open(fpath) as f_def:
                registry = registry.with_resource(
                    uri=f"definitions/{fpath.name}",
                    resource=Resource.from_contents(json.load(f_def)),
                )

    validate(instance=scenario, schema=schema, registry=registry)


# --- handle_mutate ---
@pytest.mark.asyncio
async def test_handle_mutate_exceptions(tmp_path, monkeypatch):
    from eval_runner.handlers.scenarios import handle_mutate

    monkeypatch.chdir(tmp_path)

    args = parse_args(["mutate", "--input", "ghost.json", "--type", "typo"])
    await handle_mutate(args)

    # Valid v1.2 JSON
    input_file = tmp_path / "real.json"
    input_file.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {"name": "Mutate Me", "compliance_level": "Standard"},
                "workflow": {"nodes": [{"id": "t1", "task_description": "task"}], "edges": []},
            }
        ),
        encoding="utf-8",
    )

    args = parse_args(["mutate", "--input", str(input_file), "--type", "typo"])
    with (
        patch("eval_runner.mutator.mutate_scenario", return_value={}),
        patch("eval_runner.mutator.save_mutated_scenario"),
    ):
        await handle_mutate(args)


# --- handle_failures_search ---
@pytest.mark.asyncio
async def test_handle_failures_search_basic(tmp_path, monkeypatch):
    from eval_runner.handlers.environment import handle_failures_search

    monkeypatch.chdir(tmp_path)

    args = parse_args(["failures", "search", "error"])
    await handle_failures_search(args)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    for i in range(12):
        (runs_dir / f"r{i}.jsonl").write_text("error inside file", encoding="utf-8")

    with patch("eval_runner.config.RUN_LOG_DIR", runs_dir):
        await handle_failures_search(args)


# --- handle_explain ---
@pytest.mark.asyncio
async def test_handle_explain_basic(tmp_path, monkeypatch):
    from eval_runner.handlers.analysis import handle_explain

    monkeypatch.chdir(tmp_path)

    args = parse_args(["explain", "--run-id", "ghost"])
    await handle_explain(args)

    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")

    args = parse_args(["explain", "--run-id", "real"])
    with patch(
        "eval_runner.explainer.explain_trace",
        return_value={"confidence": 0.9, "root_cause": "cpu", "suggestion": "fix"},
    ):
        await handle_explain(args)


# --- handle_calibrate ---
@pytest.mark.asyncio
async def test_handle_calibrate_basic(tmp_path, monkeypatch):
    from eval_runner.handlers.analysis import handle_calibrate

    monkeypatch.chdir(tmp_path)

    args = parse_args(["calibrate", "--run-id", "ghost"])
    await handle_calibrate(args)

    real_file = tmp_path / "real.jsonl"
    real_file.write_text("{}", encoding="utf-8")

    args = parse_args(["calibrate", "--run-id", "real"])

    with patch(
        "eval_runner.handlers.analysis.trace_utils.load_events", side_effect=Exception("Read bad")
    ):
        await handle_calibrate(args)

    with patch(
        "eval_runner.handlers.analysis.trace_utils.load_events", return_value=[{"event": "start"}]
    ):
        await handle_calibrate(args)

    with patch(
        "eval_runner.handlers.analysis.trace_utils.load_events",
        return_value=[
            {"event": "evaluation", "metric": "luna_judge_score", "value": 0.9, "human_score": 0.9},
            {"event": "evaluation", "metric": "luna_judge_score", "value": 0.8, "human_score": 0.8},
        ],
    ):
        await handle_calibrate(args)
