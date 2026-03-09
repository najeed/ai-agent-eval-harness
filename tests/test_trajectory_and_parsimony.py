"""
test_trajectory_and_parsimony.py

Unit tests for Milestone 4 features: Path Parsimony and Trajectory Capturing.
Aligned with OpenCore modular architecture and typed contexts.
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from eval_runner import metrics, engine, reporter

def test_path_parsimony_calculation():
    """Verifies the efficiency score calculation."""
    # Perfect efficiency (1 turn)
    assert metrics.calculate_path_parsimony({}, 1, 5) == 1.0
    # Worst efficiency (5 turns)
    assert metrics.calculate_path_parsimony({}, 5, 5) == 0.0
    # Middle (3 turns)
    assert metrics.calculate_path_parsimony({}, 3, 5) == 0.5
    # Edge case: max_turns = 1
    assert metrics.calculate_path_parsimony({}, 1, 1) == 1.0

@pytest.mark.asyncio
async def test_engine_captures_state_transitions():
    """Verifies that engine.py snapshots state in conversation_history."""
    # Mock scenario with a state-mutating tool
    scenario = {
        "scenario_id": "test_m4",
        "tasks": [
            {
                "task_id": "t1",
                "description": "Call update_status",
                "required_tools": ["update_status"]
            }
        ],
        "initial_state": {"status": "idle"},
        "tools": {
            "update_status": {
                "state_changes": [{"path": "status", "value": "active"}],
                "output": {"status": "success"}
            }
        }
    }
    
    # Mock agent response with a tool call
    mock_response = {
        "action": "call_tool",
        "tool_name": "update_status",
        "tool_params": {"status": "active"}
    }
    
    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock) as mock_call:
        # Turn 1: Tool call
        # Turn 2: Signal final_answer
        mock_call.side_effect = [
            mock_response,
            {"action": "final_answer", "summary": "Done"}
        ]
        
        results = await engine.run_evaluation(scenario)
        history = results[0]["conversation_history"]
        
        # Find environment entry
        env_entry = next(entry for entry in history if entry["role"] == "environment")
        assert "state_before" in env_entry
        assert env_entry["state_before"] == {"status": "idle"}
        assert "state_after" in env_entry
        assert env_entry["state_after"] == {"status": "active"}

def test_mermaid_generation():
    """Verifies that reporter.py generates a valid Mermaid string."""
    task_results = {
        "conversation_history": [
            {"role": "agent", "content": {"action": "call_tool"}},
            {"role": "environment", "content": {"status": "success"}}
        ]
    }
    mermaid = reporter.generate_mermaid_trajectory(task_results)
    assert "graph TD" in mermaid
    assert "Start((Start))" in mermaid
    assert "Turn_1_agent" in mermaid
    assert "End((End))" in mermaid

def test_trajectory_json_export(tmp_path):
    """Verifies JSON export structure."""
    scenario = {"scenario_id": "test_id", "title": "Test"}
    results = [{"task_id": "t1", "metrics": []}]
    
    # Pass tmp_path to ensure isolation
    reporter.save_trajectory(scenario, results, base_dir=tmp_path)
    
    export_files = list(tmp_path.glob("reports/trajectories/test_id_*.json"))
    assert len(export_files) == 1
    
    with open(export_files[0], "r") as f:
        data = json.load(f)
        assert data["metadata"]["scenario_id"] == "test_id"
        assert "results" in data
