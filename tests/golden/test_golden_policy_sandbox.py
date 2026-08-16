"""
tests/golden/test_golden_policy_sandbox.py
Golden Verification Corpus: Policy Sandbox Constraint Generalization
"""

import pytest

from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_golden_policy_arbitrary_numeric_keys(tmp_path):
    scenario = {
        "policies": {
            "transfer_funds": {"max_limit": 100.0, "constrained_params": ["quantity", "volume"]},
            "allocate_tokens": {"max_limit": 50.0},
        },
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "task",
                    "required_tools": ["transfer_funds", "allocate_tokens"],
                }
            ],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path)

    # 1. Non-amount key 'quantity' exceeding limit
    res1 = await sandbox.execute("transfer_funds", {"quantity": 250.0})
    assert res1["status"] == "policy_violation"
    assert "quantity" in res1["violation"]
    assert "exceeds limit" in res1["violation"]

    # 2. Non-amount key 'volume' within limit
    res2 = await sandbox.execute("transfer_funds", {"volume": 80.0})
    assert res2["status"] == "success"

    # 3. Dynamic numeric key autodetection on 'allocate_tokens' (e.g. 'token_count')
    res3 = await sandbox.execute("allocate_tokens", {"token_count": 99.0})
    assert res3["status"] == "policy_violation"
    assert "token_count" in res3["violation"]

    # 4. Dynamic numeric key within limit
    res4 = await sandbox.execute("allocate_tokens", {"token_count": 25.0})
    assert res4["status"] == "success"
