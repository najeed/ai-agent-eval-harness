"""
test_tool_sandbox.py

Test suite for the ToolSandbox mock tool execution environment.
Aligned with OpenCore modular architecture and explicit tool definitions.
"""

import pytest
import sys
from pathlib import Path

from eval_runner.tool_sandbox import ToolSandbox

def test_sandbox_known_tool():
    """Test that a known tool returns the expected result from the scenario."""
    scenario = {
        "tools": {
            "get_customer_details": {
                "output": {"status": "success", "tool_name": "get_customer_details", "data": "info"}
            }
        },
        "tasks": [{"required_tools": ["get_customer_details"]}]
    }
    sandbox = ToolSandbox(scenario)

    result = sandbox.execute("get_customer_details", {"customer_id": "cust_123"})
    assert result["status"] == "success"
    assert result["tool_name"] == "get_customer_details"

def test_sandbox_unknown_tool():
    """Test that an unknown tool returns a default or success message (per current impl)."""
    # Current implementation returns a default success if not found.
    # To test 'error', we can define a tool that returns error or change ToolSandbox.
    scenario = {"tasks": [{"required_tools": ["get_customer_details"]}]}
    sandbox = ToolSandbox(scenario)

    result = sandbox.execute("nonexistent_tool", {})
    assert result["status"] == "success" # Default behavior in updated tool_sandbox.py
    assert "Executed nonexistent_tool" in result["message"]

def test_sandbox_state_initialization():
    """Test that state is initialized correctly from the scenario."""
    scenario = {
        "initial_state": {"customer_name": "Jane Doe", "balance": 100},
        "tasks": [{"required_tools": ["any_tool"]}]
    }
    sandbox = ToolSandbox(scenario)
    assert sandbox.state == {"customer_name": "Jane Doe", "balance": 100}

def test_sandbox_state_mutation():
    """Test that explicit 'state_changes' mutate the state."""
    scenario = {
        "initial_state": {"current_plan": "Basic"},
        "tools": {
            "update_plan": {
                "state_changes": [{"path": "current_plan", "value": "Premium"}],
                "output": {"status": "success"}
            }
        },
        "tasks": [{"required_tools": ["update_plan"]}]
    }
    sandbox = ToolSandbox(scenario)

    # update_plan
    sandbox.execute("update_plan", {"current_plan": "Premium"})
    assert sandbox.state["current_plan"] == "Premium"

def test_sandbox_lifecycle():
    """Verify setup/teardown exist (even if noop in ToolSandbox)."""
    sandbox = ToolSandbox({"tasks": []})
    sandbox.setup()
    sandbox.teardown()
    assert True # Just verifying they are callable
