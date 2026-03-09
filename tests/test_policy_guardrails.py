
import pytest
from eval_runner.tool_sandbox import ToolSandbox

def test_policy_enforcement_success():
    scenario = {
        "policies": {
            "apply_refund": {"max_limit": 50.0}
        },
        "tasks": [{"required_tools": ["apply_refund"]}]
    }
    sandbox = ToolSandbox(scenario)

    # Within limit
    result = sandbox.execute("apply_refund", {"amount": 40.0})
    assert result["status"] == "success"

    # Exceeds limit
    result = sandbox.execute("apply_refund", {"amount": 100.0})
    assert result["status"] == "policy_violation"
    assert "exceeds limit of 50.0" in result["violation"]

def test_policy_enforcement_no_policy():
    scenario = {
        "policies": {},
        "tasks": [{"required_tools": ["apply_refund"]}]
    }
    sandbox = ToolSandbox(scenario)

    # No policy for this tool
    result = sandbox.execute("apply_refund", {"amount": 100.0})
    assert result["status"] == "success"
