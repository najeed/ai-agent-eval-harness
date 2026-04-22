"""
test_coverage_expansion.py

Targeted tests to fill coverage gaps in CLI and Console routes.
Focuses on handle_verify, handle_analyze, classify_scenario, and demo context routes.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.cli import get_parser
from eval_runner.console.routes import get_loan_demo_context
from eval_runner.handlers.evaluation import handle_verify
from eval_runner.handlers.scenarios import classify_scenario


@pytest.fixture
def parser():
    p, _, _, _ = get_parser()
    return p


# --- CLI Gaps ---


@pytest.mark.asyncio
async def test_handle_analyze_direct(monkeypatch, tmp_path):
    """Hits handle_analyze in cli.py directly."""
    from eval_runner.handlers.environment import handle_analyze

    mock_analyze = AsyncMock()
    monkeypatch.setattr("eval_runner.analyzer.analyze_repo", mock_analyze)

    args = MagicMock()
    args.path = str(tmp_path)
    args.output = str(tmp_path / "out.json")

    await handle_analyze(args)
    mock_analyze.assert_called_once()


def test_classify_scenario_helper(monkeypatch):
    """Hits classify_scenario logic in scenarios.py."""
    import sys

    # 1. Mock the entire module in sys.modules to prevent real import/crash
    mock_st_class = MagicMock()
    mock_util = MagicMock()
    mock_module = MagicMock()
    mock_module.SentenceTransformer = mock_st_class
    mock_module.util = mock_util

    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_module)

    # 2. Setup the mock model behavior
    mock_model = MagicMock()
    # Return a dummy similarity vector (5 elements for the 5 industries in scenarios.py)
    mock_model.encode.return_value = MagicMock()
    mock_st_class.return_value = mock_model

    # Mock util.cos_sim to return a tensor-like object with argmax
    mock_sim = MagicMock()
    mock_sim.__getitem__.return_value.argmax.return_value = 0  # finance
    mock_sim.__getitem__.return_value.__getitem__.return_value = 0.95
    mock_util.cos_sim.return_value = mock_sim

    # 3. Execute target logic
    scenario = {"title": "Loan Application", "description": "Test financial scenario"}
    res = classify_scenario(scenario)

    # 4. Assertions
    assert "industry" in res
    assert res["industry"] == "finance"


@pytest.mark.asyncio
async def test_handle_verify_direct(tmp_path):
    """Hits handle_verify branch in cli.py."""
    trace_file = tmp_path / "test.jsonl"
    trace_file.write_text(json.dumps({"event": "run_start", "metadata": {"sha256": "fake"}}) + "\n")

    args = MagicMock()
    args.scenario = str(trace_file)
    args.path = str(trace_file)
    args.manifest = None

    with patch(
        "eval_runner.artifact_plugin.ArtifactPlugin.verify_integrity", return_value=(True, [])
    ):
        res = await handle_verify(args)
        assert res == 1


# --- Console Gaps ---


def test_get_loan_demo_context():
    """Hits get_loan_demo_context in routes.py."""
    from flask import Flask

    app = Flask(__name__)
    api_key = "test-key"
    with (
        patch("eval_runner.config.DASHBOARD_API_KEY", api_key),
        patch("eval_runner.config.SERVICE_API_KEY", api_key),
    ):
        with app.test_request_context(headers={"X-AES-API-KEY": api_key}):
            ctx = get_loan_demo_context()
            # If wrapped by require_permission, it might return a tuple or Response
            if isinstance(ctx, tuple):
                status_code = ctx[1]
            else:
                status_code = ctx.status_code
            assert status_code == 200


# --- Engine Gaps ---


@pytest.mark.asyncio
async def test_call_agent_error_branches():
    """Hits error branches in engine.py call_agent."""
    from eval_runner.engine import AgentAdapterRegistry

    registry = AgentAdapterRegistry()

    # Test missing adapter
    with patch.dict(registry._adapters, {}, clear=True):
        with pytest.raises(ValueError, match="No adapter registered"):
            await registry.call_agent({"task_description": "hi"}, protocol="nonexistent")
