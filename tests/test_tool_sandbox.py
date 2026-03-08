"""
Test suite for the ToolSandbox mock tool execution environment.

This module tests that the sandbox correctly handles known and unknown tools,
and properly initializes its tool inventory from scenario data.

Example:
    pytest tests/test_tool_sandbox.py -v
"""

import pytest
import sys
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

from tool_sandbox import ToolSandbox


def test_sandbox_known_tool():
    """Test that a known tool returns a success result."""
    scenario = {
        "tasks": [
            {"required_tools": ["get_customer_details", "run_line_test"]},
            {"required_tools": ["provide_wifi_optimization_guide"]},
        ]
    }
    sandbox = ToolSandbox(scenario)

    result = sandbox.execute("get_customer_details", {"customer_id": "cust_123"})
    assert result["status"] == "success"
    assert result["tool_name"] == "get_customer_details"
    assert result["params_received"] == {"customer_id": "cust_123"}


def test_sandbox_unknown_tool():
    """Test that an unknown tool returns an error result."""
    scenario = {"tasks": [{"required_tools": ["get_customer_details"]}]}
    sandbox = ToolSandbox(scenario)

    result = sandbox.execute("nonexistent_tool", {})
    assert result["status"] == "error"
    assert "not available" in result["output"]


def test_sandbox_collects_tools_across_tasks():
    """Test that the sandbox aggregates tools from all tasks in the scenario."""
    scenario = {
        "tasks": [
            {"required_tools": ["tool_a"]},
            {"required_tools": ["tool_b", "tool_c"]},
            {"required_tools": ["tool_a"]},  # Duplicate
        ]
    }
    sandbox = ToolSandbox(scenario)
    assert sandbox.known_tools == {"tool_a", "tool_b", "tool_c"}


def test_sandbox_empty_scenario():
    """Test that the sandbox handles a scenario with no tasks."""
    sandbox = ToolSandbox({"tasks": []})
    assert sandbox.known_tools == set()

    result = sandbox.execute("any_tool")
    assert result["status"] == "error"


def test_sandbox_default_params():
    """Test that execute works with no params argument."""
    scenario = {"tasks": [{"required_tools": ["tool_x"]}]}
    sandbox = ToolSandbox(scenario)

    result = sandbox.execute("tool_x")
    assert result["status"] == "success"
    assert result["params_received"] == {}

def test_sandbox_state_initialization():
    """Test that state is initialized correctly from the scenario."""
    scenario = {
        "initial_state": {"customer_name": "Jane Doe", "balance": 100},
        "tasks": [{"required_tools": ["any_tool"]}]
    }
    sandbox = ToolSandbox(scenario)
    assert sandbox.state == {"customer_name": "Jane Doe", "balance": 100}


def test_sandbox_state_mutation():
    """Test that 'update_' and 'set_' tools mutate the state."""
    scenario = {
        "initial_state": {"current_plan": "Basic"},
        "tasks": [{"required_tools": ["update_plan", "set_balance"]}]
    }
    sandbox = ToolSandbox(scenario)

    # update_
    sandbox.execute("update_plan", {"current_plan": "Premium"})
    assert sandbox.state["current_plan"] == "Premium"

    # set_
    sandbox.execute("set_balance", {"amount": 500})
    assert sandbox.state["amount"] == 500


