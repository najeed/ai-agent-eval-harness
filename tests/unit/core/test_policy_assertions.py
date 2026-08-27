"""
A4: Sandbox policy decisions become first-class policy assertions.

Every ToolSandbox policy evaluation (allowed AND denied) is recorded with:
  id          — the policy identifier from the evaluator verdict
  input_hash  — sha3_256:<hex> commitment over canonical tool+params JSON
  decision    — "allowed" | "denied"
  reason      — human-readable explanation
  evidence    — the full evaluator result dict

At session level the per-node task results expose these as `policy_checks`
and a denial is gating: a node can never be reported successful while one of
its tool calls was denied by policy.
"""

import json

import pytest

from eval_runner.tool_sandbox import ToolSandbox


@pytest.fixture
def guarded_scenario():
    return {
        "aes_version": 1.4,
        "initial_state": {"balance": 500},
        "tools": {"transfer_funds": {"output": {"status": "success", "message": "transferred"}}},
        "metadata": {
            "policies": {
                "transfer_funds": {
                    "id": "max_transfer_limit",
                    "max_limit": 1000,
                    "constrained_params": "amount",
                }
            }
        },
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "move money",
                    "required_tools": ["transfer_funds"],
                }
            ],
            "edges": [],
        },
    }


def _make_sandbox(scenario, tmp_path):
    return ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")


@pytest.mark.asyncio
async def test_allowed_decision_recorded_as_first_class_assertion(guarded_scenario, tmp_path):
    sandbox = _make_sandbox(guarded_scenario, tmp_path)
    result = await sandbox.execute("transfer_funds", {"amount": 250})

    assert result["status"] == "success"
    assert len(sandbox.policy_decisions) == 1

    decision = sandbox.policy_decisions[0]
    assert decision["decision"] == "allowed"
    assert decision["id"]
    assert decision["input_hash"].startswith("sha3_256:")
    assert decision["reason"]
    assert isinstance(decision["evidence"], dict)
    assert decision["tool_name"] == "transfer_funds"


@pytest.mark.asyncio
async def test_denied_decision_recorded_and_reported(guarded_scenario, tmp_path):
    sandbox = _make_sandbox(guarded_scenario, tmp_path)
    result = await sandbox.execute("transfer_funds", {"amount": 99999})

    assert result["status"] == "policy_violation"
    assert len(sandbox.policy_decisions) == 1

    decision = sandbox.policy_decisions[0]
    assert decision["decision"] == "denied"
    assert decision["input_hash"].startswith("sha3_256:")
    # Evidence carries the evaluator's structured verdict.
    assert decision["evidence"] == result["details"]


@pytest.mark.asyncio
async def test_input_hash_binds_exact_inputs(guarded_scenario, tmp_path):
    sandbox = _make_sandbox(guarded_scenario, tmp_path)
    await sandbox.execute("transfer_funds", {"amount": 250})
    await sandbox.execute("transfer_funds", {"amount": 251})

    h1 = sandbox.policy_decisions[0]["input_hash"]
    h2 = sandbox.policy_decisions[1]["input_hash"]

    # Deterministic commitments: same inputs -> same hash, different inputs -> differ.
    assert h1 != h2

    import hashlib

    expected = hashlib.sha3_256(
        json.dumps({"tool": "transfer_funds", "params": {"amount": 250}}, sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()
    assert h1 == f"sha3_256:{expected}"


@pytest.mark.asyncio
async def test_unpoliced_tool_records_no_decision(guarded_scenario, tmp_path):
    scenario = dict(guarded_scenario)
    scenario["tools"]["unpoliced_tool"] = {"output": {"status": "success"}}
    sandbox = _make_sandbox(scenario, tmp_path)

    await sandbox.execute("unpoliced_tool", {})
    assert sandbox.policy_decisions == []
