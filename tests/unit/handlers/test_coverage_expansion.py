"""
test_coverage_expansion.py

Targeted tests to fill coverage gaps in CLI and Console routes.
Focuses on handle_verify, handle_analyze, classify_scenario, and demo context routes.
"""

import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner.cli import get_parser
from eval_runner.handlers.evaluation import handle_verify
from eval_runner.handlers.scenarios import classify_scenario
from eval_runner.console.routes import get_loan_demo_context

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

def test_classify_scenario_helper():
    """Hits classify_scenario logic in cli.py."""
    # We mock SentenceTransformer to avoid heavy ML loading in unit tests
    with patch("sentence_transformers.SentenceTransformer") as mock_st:
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.9, 0.1, 0.0]] # Mock cosine similarity
        mock_st.return_value = mock_model
        
        scenario = {"title": "Loan Application", "description": "Test financial scenario"}
        res = classify_scenario(scenario)
        # res should return a dict with top-matched industry
        assert "industry" in res

def test_handle_verify_direct(tmp_path):
    """Hits handle_verify branch in cli.py."""
    trace_file = tmp_path / "test.jsonl"
    trace_file.write_text(json.dumps({"event": "run_start", "metadata": {"sha256": "fake"}}) + "\n")
    
    args = MagicMock()
    args.scenario = str(trace_file)
    
    with patch("eval_runner.artifact_plugin.ArtifactPlugin.verify_integrity", return_value=(True, [])):
        handle_verify(args)

# --- Console Gaps ---

def test_get_loan_demo_context():
    """Hits get_loan_demo_context in routes.py."""
    from flask import Flask
    app = Flask(__name__)
    with app.app_context():
        ctx = get_loan_demo_context()
        assert ctx.status_code == 200

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

@pytest.mark.asyncio
async def test_human_adapter_branch():
    """Hits the _human_adapter branch in engine.py."""
    from eval_runner.engine import AgentAdapterRegistry
    registry = AgentAdapterRegistry()
    
    with patch("builtins.input", return_value="human response"):
        # Provide a dummy endpoint to satisfy the check in engine.py
        res = await registry.call_agent({"task_description": "hi"}, protocol="human", endpoint="dummy")
        assert res["action"] == "hitl_pause"
        assert "Waiting for human" in res["message"]
