"""
test_trajectory_and_parsimony.py

Unit tests for Milestone 4 features: Path Parsimony and Trajectory Capturing.
Aligned with OpenCore modular architecture and typed contexts.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner import engine, metrics, reporter


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
        "id": "test_scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "Call update_status",
                    "required_tools": ["update_status"],
                }
            ],
            "edges": [],
        },
        "initial_state": {"status": "idle"},
        "tools": {
            "update_status": {
                "state_changes": [{"path": "status", "value": "active"}],
                "output": {"status": "success"},
            }
        },
    }

    # Mock agent response with a tool call
    mock_response = {
        "action": "call_tool",
        "tool_name": "update_status",
        "tool_params": {"status": "active"},
    }

    with (
        patch(
            "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_call,
        patch("eval_runner.plugins.manager.plugins", []),
    ):
        # Turn 1: Tool call
        # Turn 2: Signal final_answer
        mock_call.side_effect = [
            mock_response,
            {"action": "final_answer", "summary": "Done"},
        ]

        # We also need to avoid real ToolSandbox.execute if it tries to do anything fancy,
        # but the default ToolSandbox doesn't require Docker.
        # The logs showed EnterprisePlugin was the one doing it.
        # So mocking plugins list should fix it.

        # O(N) Forensics Sync: Verify state is captured in forensics sidecars, not history
        results = await engine.run_evaluation(scenario, run_id="test_trajectory_core")

        from eval_runner import config

        forensics_dir = config.RUN_LOG_DIR / "test_trajectory_core" / "forensics"

        # Turn 1 tool call produces two snapshots (before/after) in this implementation
        state_before_path = forensics_dir / "state_turn_001.json"
        # Turn + 1000 offset is used for the "after" snapshot in the refined session logic
        state_after_path = forensics_dir / "state_turn_1001.json"

        assert state_before_path.exists()
        with open(state_before_path) as f:
            assert json.load(f) == {"status": "idle"}

        assert state_after_path.exists()
        with open(state_after_path) as f:
            assert json.load(f) == {"status": "active"}

        history = results[0]["conversation_history"]
        # Verify history is clean of heavy state blobs
        for entry in history:
            assert "state_before" not in entry
            assert "state_after" not in entry


def test_mermaid_generation():
    """Verifies that reporter.py generates a valid Mermaid string."""
    task_results = {
        "conversation_history": [
            {"role": "agent", "content": {"action": "call_tool"}},
            {"role": "environment", "content": {"status": "success"}},
        ]
    }
    mermaid = reporter.generate_mermaid_trajectory(task_results)
    assert "graph TD" in mermaid
    assert "Start((Start))" in mermaid
    assert "Turn_1_agent" in mermaid
    assert "End((End))" in mermaid


def test_trajectory_json_export(tmp_path):
    """Verifies JSON export structure."""
    scenario = {
        "id": "test_hitl_ci",
        "workflow": {"nodes": [{"id": "task1", "task_description": "test"}], "edges": []},
    }
    results = [{"task_id": "t1", "metrics": []}]

    # Pass tmp_path to ensure isolation
    reporter.save_trajectory(scenario, results, base_dir=tmp_path)

    export_files = list(tmp_path.glob("reports/trajectories/test_hitl_ci_*.json"))
    assert len(export_files) == 1

    import traceback

    try:
        with open(export_files[0]) as f:
            content = f.read()
            print(f"\n[DEBUG] Read {len(content)} bytes from {export_files[0]}")
            data = json.loads(content)
            assert data["metadata"]["id"] == "test_hitl_ci"
            assert "results" in data
    except ValueError as e:
        print(f"\n[CRITICAL] ValueError at {export_files[0]}: {e}")
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"\n[ERROR] Unexpected error at {export_files[0]}: {e}")
        traceback.print_exc()
        raise
