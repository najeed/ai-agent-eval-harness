import pytest

from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_sandbox_grounding_hits():
    scenario = {
        "tools": {"search": {"output": {"status": "success"}}},
        "policies": {"search": {"max_limit": 5}},
    }
    sandbox = ToolSandbox(scenario)

    # Execute tool
    await sandbox.execute("search", {"query": "test"})

    assert sandbox.grounding_hits["tools"]["search"] == 1
    assert sandbox.grounding_hits["policies"]["search"] == 1

    # Execute again
    await sandbox.execute("search", {"query": "test2"})
    assert sandbox.grounding_hits["tools"]["search"] == 2
    assert sandbox.grounding_hits["policies"]["search"] == 2


@pytest.mark.asyncio
async def test_sandbox_missing_policy_hit():
    scenario = {"tools": {"no_policy_tool": {"output": {"status": "success"}}}}
    sandbox = ToolSandbox(scenario)
    await sandbox.execute("no_policy_tool", {})

    assert sandbox.grounding_hits["tools"]["no_policy_tool"] == 1
    assert "no_policy_tool" not in sandbox.grounding_hits["policies"]
