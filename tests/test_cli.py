"""
test_cli.py

Unit tests for the Onboarding CLI (eval_runner.cli).
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from eval_runner import cli

def test_detect_framework_langgraph(tmp_path):
    """Verifies LangGraph detection logic."""
    with patch("eval_runner.cli.Path.cwd", return_value=tmp_path):
        # By file
        (tmp_path / "langgraph.json").write_text("{}")
        assert cli.detect_framework() == "LangGraph"
        
        (tmp_path / "langgraph.json").unlink()
        (tmp_path / "nodes.py").write_text("# nodes")
        assert cli.detect_framework() == "LangGraph"
        
        # By requirements
        (tmp_path / "nodes.py").unlink()
        (tmp_path / "requirements.txt").write_text("langgraph==0.1.0")
        assert cli.detect_framework() == "LangGraph"

def test_detect_framework_crewai(tmp_path):
    """Verifies CrewAI detection logic."""
    with patch("eval_runner.cli.Path.cwd", return_value=tmp_path):
        # By file
        (tmp_path / "crew.py").write_text("# crew")
        assert cli.detect_framework() == "CrewAI"
        
        (tmp_path / "crew.py").unlink()
        (tmp_path / "agents.yaml").write_text("agents: []")
        assert cli.detect_framework() == "CrewAI"
        
        # By requirements
        (tmp_path / "agents.yaml").unlink()
        (tmp_path / "requirements.txt").write_text("crewai")
        assert cli.detect_framework() == "CrewAI"

def test_detect_framework_custom(tmp_path):
    """Verifies fallback to Custom if no framework signals are found."""
    with patch("eval_runner.cli.Path.cwd", return_value=tmp_path):
        assert cli.detect_framework() == "Custom"

def test_handle_init_scaffolding(tmp_path, monkeypatch):
    """Tests the init wizard's file generation."""
    # Mock inputs: Industry '1' (accounting), API URL (default)
    inputs = iter(["1", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    
    # Run init in temporary directory
    os.chdir(tmp_path)
    
    # We need to mock list_industries to return a known list
    with patch("eval_runner.cli.list_industries", return_value=["accounting", "telecom"]):
        cli.handle_init(None)
        
    # Verify eval_config.json
    config_path = tmp_path / "eval_config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["industry"] == "accounting"
    assert config["agent_api_url"] == "http://localhost:5001/execute_task"
    
    # Verify scenarios directory
    scenario_dir = tmp_path / "scenarios"
    assert scenario_dir.exists()
    assert (scenario_dir / "starter_scenario.json").exists()
