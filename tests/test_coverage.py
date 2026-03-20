import pytest
from eval_runner.tool_sandbox import ToolSandbox


def test_sandbox_grounding_hits():
    scenario = {
        "tools": {"search": {"output": {"status": "success"}}},
        "policies": {"search": {"max_limit": 5}},
    }
    sandbox = ToolSandbox(scenario)

    # Execute tool
    sandbox.execute("search", {"query": "test"})

    assert sandbox.grounding_hits["tools"]["search"] == 1
    assert sandbox.grounding_hits["policies"]["search"] == 1

    # Execute again
    sandbox.execute("search", {"query": "test2"})
    assert sandbox.grounding_hits["tools"]["search"] == 2
    assert sandbox.grounding_hits["policies"]["search"] == 2


def test_sandbox_missing_policy_hit():
    scenario = {"tools": {"no_policy_tool": {"output": {"status": "success"}}}}
    sandbox = ToolSandbox(scenario)
    sandbox.execute("no_policy_tool", {})

    assert sandbox.grounding_hits["tools"]["no_policy_tool"] == 1
    assert "no_policy_tool" not in sandbox.grounding_hits["policies"]
