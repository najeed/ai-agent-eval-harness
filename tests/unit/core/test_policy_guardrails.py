import pytest
from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_policy_enforcement_success():
    scenario = {
        "policies": {"apply_refund": {"max_limit": 50.0}},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["apply_refund"]}],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario)

    # Within limit
    result = await sandbox.execute("apply_refund", {"amount": 40.0})
    assert result["status"] == "success"

    # Exactly at limit
    result = await sandbox.execute("apply_refund", {"amount": 50.0})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_policy_enforcement_violation():
    scenario = {
        "policies": {"apply_refund": {"max_limit": 50.0}},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["apply_refund"]}],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario)

    # Over limit
    result = await sandbox.execute("apply_refund", {"amount": 100.0})
    assert result["status"] == "policy_violation"
    assert "exceeds limit" in result["violation"]


@pytest.mark.asyncio
async def test_policy_enforcement_no_policy():
    scenario = {
        "policies": {},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["apply_refund"]}],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario)

    # No policy for this tool
    result = await sandbox.execute("apply_refund", {"amount": 100.0})
    assert result["status"] == "success"
