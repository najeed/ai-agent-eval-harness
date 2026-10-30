"""Policy evidence and write interception preserve tool execution semantics."""

import hashlib
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from eval_runner.interfaces.policy import PolicyEvaluationResult, PolicyEvaluator
from eval_runner.tool_sandbox import ToolSandbox


class FixedPolicy(PolicyEvaluator):
    def __init__(self, allowed, violations=None):
        self.allowed = allowed
        self.violations = violations or []

    def validate_policy(self, policy_spec):
        return True

    def evaluate_policy(self, policy_spec, input_data, context=None):
        return PolicyEvaluationResult(
            self.allowed, "transfer-policy", reason="approval required", violations=self.violations
        )


def sandbox_for(tmp_path, *, allowed, plugin=None, writable=True, violations=None):
    tool = {"output": {"status": "success", "balance": 100}}
    if writable:
        tool["state_changes"] = [{"path": "balance", "value": 75}]
    return ToolSandbox(
        {
            "id": "policy-contract",
            "initial_state": {"balance": 100},
            "tools": {"transfer": tool},
            "metadata": {"policies": {"transfer": {}}},
        },
        workspace_root=tmp_path,
        jail_root=tmp_path / "jail",
        policy_evaluator=FixedPolicy(allowed, violations),
        plugin_manager=plugin,
        event_bus=MagicMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("violations", [[], [{"field": "amount"}], [{"limit": 10}]])
async def test_policy_denial_without_detailed_violations_still_blocks_the_write(
    tmp_path, violations
):
    sandbox = sandbox_for(tmp_path, allowed=False, violations=violations)

    response = await sandbox.execute("transfer", {"amount": 25})

    assert response["status"] == "policy_violation"
    assert response["violation"] == "approval required"
    assert sandbox.state["balance"] == 100
    assert sandbox.policy_decisions[0]["decision"] == "denied"


@pytest.mark.asyncio
async def test_policy_input_commitment_supports_yaml_date_values(tmp_path):
    sandbox = sandbox_for(tmp_path, allowed=True)
    params = {"amount": 25, "booked_at": date(2026, 10, 29)}

    response = await sandbox.execute("transfer", params)

    expected = hashlib.sha3_256(
        json.dumps({"tool": "transfer", "params": params}, sort_keys=True, default=str).encode()
    ).hexdigest()
    assert response["status"] == "success"
    assert sandbox.policy_decisions[0]["input_hash"] == "sha3_256:" + expected
    assert sandbox.state["balance"] == 75


@pytest.mark.asyncio
async def test_write_veto_does_not_prevent_a_read_only_tool(tmp_path):
    plugin = SimpleNamespace(
        trigger_interceptor=lambda *args: False, last_rejection_reason="writes require approval"
    )
    sandbox = sandbox_for(tmp_path, allowed=True, plugin=plugin, writable=False)

    response = await sandbox.execute("transfer", {})

    assert response == {"status": "success", "balance": 100}
    assert sandbox.state == {"balance": 100}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("interception", "expected_balance", "allowed"),
    [
        (None, 75, True),
        ({"allowed": True}, 75, True),
        ({"allowed": True, "state_diff": {"balance": 50}}, 50, True),
        (False, 100, False),
        ({"allowed": False}, 100, False),
    ],
)
async def test_commit_interceptor_decision_controls_the_observed_state(
    tmp_path, interception, expected_balance, allowed
):
    plugin = SimpleNamespace(trigger_interceptor=lambda *args: interception)
    sandbox = sandbox_for(tmp_path, allowed=True, plugin=plugin)

    response = await sandbox.execute("transfer", {})

    assert response["status"] == ("success" if allowed else "error")
    if not allowed:
        assert response["error_code"] == "STATE_COMMIT_REJECTED"
    assert sandbox.state["balance"] == expected_balance


@pytest.mark.asyncio
async def test_malformed_intercepted_diff_is_rejected_before_any_state_write(tmp_path):
    plugin = SimpleNamespace(trigger_interceptor=lambda *args: {"allowed": True, "state_diff": []})
    sandbox = sandbox_for(tmp_path, allowed=True, plugin=plugin)

    with pytest.raises(TypeError, match="state_diff must be a mapping"):
        await sandbox.execute("transfer", {})
    assert sandbox.state == {"balance": 100}
