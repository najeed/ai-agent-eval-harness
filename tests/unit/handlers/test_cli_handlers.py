import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.handlers import analysis, environment, evaluation, scenarios


@pytest.fixture
def physical_env(tmp_path):
    """
    Standardized Physical Environment for Zero-Mock Verification.
    """
    root = tmp_path / "root"
    root.mkdir()
    return root


@pytest.fixture
def mock_args():
    return Namespace(
        industry="finance",
        format="json",
        days=7,
        input="input.json",
        output_dir="output",
        query="test",
        standard=None,
        scenario_path="scen.json",
        search="test",
        refresh=False,
        target="scen.json",
    )


@pytest.mark.asyncio
async def test_handle_list(mock_args):
    """Test 'list' command handler. Forensic: Patch ScenarioCatalog to avoid OSError."""
    with (
        patch("eval_runner.handlers.scenarios.catalog.ScenarioCatalog"),
        patch("eval_runner.handlers.scenarios.catalog.list_scenarios") as mock_list,
    ):
        mock_args.search = "test"
        mock_args.refresh = False
        await scenarios.handle_list(mock_args)
        mock_list.assert_called_once_with(query="test")


@pytest.mark.asyncio
async def test_handle_doctor(mock_args, capsys):
    """Test 'doctor' command handler."""
    with patch(
        "eval_runner.handlers.environment.doctor.run_doctor", new_callable=AsyncMock
    ) as mock_run:
        await environment.handle_doctor(mock_args)
        mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_cleanup_runs(mock_args, tmp_path):
    """Test 'cleanup-runs' command handler."""
    with patch("eval_runner.handlers.environment.cleaner.cleanup_traces") as mock_cleanup:
        mock_args.dir = str(tmp_path)
        await environment.handle_cleanup_runs(mock_args)
        mock_cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_handle_inspect(mock_args, capsys, tmp_path):
    """Test 'inspect' command handler. Forensic: v1.2 Numerical Schema + Node desc."""
    scen_path = tmp_path / "scen.json"
    scen_path.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {"name": "Inspect Me", "compliance_level": "Standard"},
                "workflow": {
                    "nodes": [{"id": "t1", "task_description": "First Task"}],
                    "edges": [],
                },
            }
        )
    )
    mock_args.scenario_path = str(scen_path)
    await scenarios.handle_inspect(mock_args)
    captured = capsys.readouterr()
    assert "Inspect Me" in captured.out


@pytest.mark.asyncio
async def test_handle_lint(mock_args, capsys, tmp_path):
    """Test 'lint' command handler. Forensic: v1.2 Numerical Schema."""
    scen_path = tmp_path / "scen.json"
    scen_path.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {"name": "Lint Me", "compliance_level": "Standard"},
                "workflow": {
                    "nodes": [{"id": "t1", "task_description": "Valid Task"}],
                    "edges": [],
                },
            }
        )
    )
    mock_args.target = str(scen_path)
    with patch("eval_runner.handlers.scenarios.linter.run_lint") as mock_lint:
        await scenarios.handle_lint(mock_args)
        mock_lint.assert_called_once()


@pytest.mark.asyncio
async def test_handle_export(mock_args, capsys):
    """Test 'export' command handler."""
    mock_args.input = "trace.jsonl"
    mock_args.output = "dataset.json"
    with patch("eval_runner.exporter.HFExporter.export") as mock_export:
        await environment.handle_export(mock_args)
        mock_export.assert_called_once_with("trace.jsonl", "dataset.json")


@pytest.mark.asyncio
async def test_handle_taxonomy(mock_args, capsys):
    """Test 'taxonomy' command handler. Forensic alignment: Verify header string."""
    await analysis.handle_taxonomy(mock_args)
    captured = capsys.readouterr()
    assert "AGENT-EVAL FAILURE TAXONOMY" in captured.out


@pytest.mark.asyncio
async def test_handle_verify_missing(capsys, physical_env, monkeypatch):
    """Test 'verify' with missing file. Forensic alignment: Uses [CRITICAL] string."""
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", physical_env)
    runs_dir = physical_env / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", runs_dir)

    # Passing a run-id that doesn't exist in the physical runs/ directory
    args = Namespace(run_id="missing_run", path=None, manifest=None)
    result = await evaluation.handle_verify(args)
    assert result == 1
    captured = capsys.readouterr()
    assert (
        "[CRITICAL] FAILED: Trace file for missing_run missing after vault lookup."
    ) in captured.out


@pytest.mark.asyncio
async def test_handle_import_drift(mock_args, capsys):
    """Test 'import-drift' command handler. Forensic: Full-stack scenario drift analysis."""
    mock_args.input = "trace.jsonl"
    mock_args.industry = "telecom"
    mock_args.output_dir = "scenarios"
    with patch(
        "eval_runner.handlers.scenarios.drift_importer.import_trace_as_scenario"
    ) as mock_import:
        await scenarios.handle_import_drift(mock_args)
        mock_import.assert_called_once_with(Path("trace.jsonl"), "telecom", Path("scenarios"))
