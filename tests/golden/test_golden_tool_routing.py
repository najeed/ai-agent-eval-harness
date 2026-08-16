"""
tests/golden/test_golden_tool_routing.py
Golden Verification Corpus: Tool Definition Routing & Truthiness Validation
"""

import pytest

from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_golden_empty_tool_def_not_routed_to_simulator(tmp_path):
    # Tool 'defined_empty' has an empty definition dict {}
    # It must NOT be misrouted to active_simulators lookup
    scenario = {
        "tools": {
            "defined_empty": {},
            "defined_with_output": {"output": {"status": "success", "message": "custom output"}},
        },
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "task",
                    "required_tools": ["defined_empty", "defined_with_output"],
                }
            ],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path)

    # 1. Execute defined_empty -> Should execute as tool (default output),
    # NOT fail with simulator missing
    res1 = await sandbox.execute("defined_empty", {})
    assert res1["status"] == "success"
    assert "Executed defined_empty" in res1.get("message", "")

    # 2. Execute defined_with_output
    res2 = await sandbox.execute("defined_with_output", {})
    assert res2["status"] == "success"
    assert res2.get("message") == "custom output"

    # 3. Verify grounding hits tracked tool execution
    assert sandbox.grounding_hits["tools"]["defined_empty"] == 1
    assert sandbox.grounding_hits["tools"]["defined_with_output"] == 1
