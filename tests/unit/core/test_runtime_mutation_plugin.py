"""
tests.unit.core.test_runtime_mutation_plugin
============================================
Comprehensive test suite for RuntimeMutationPlugin and the Southbound
Interception Architecture across tool dispatch, state commits, rollbacks,
and human-in-the-loop approvals.
"""

from __future__ import annotations

import pytest

from eval_runner.mutator_plugin import RuntimeMutationPlugin
from eval_runner.plugins import PluginManager
from eval_runner.session_components.approval_manager import SessionApprovalManager


@pytest.fixture
def sample_node() -> dict:
    return {
        "id": "transfer_node",
        "task_description": "Transfer funds to beneficiary",
        "parameters": {"amount": 500.0, "account": "ACC_1001"},
    }


def test_plugin_step_lifecycle(sample_node):
    """Verifies on_step_start and on_step_end tracking."""
    plugin = RuntimeMutationPlugin()
    assert plugin.step_index == 0
    assert plugin.active_node_id is None

    plugin.on_step_start(None, "transfer_node", sample_node)
    assert plugin.step_index == 1
    assert plugin.active_node_id == "transfer_node"
    assert plugin.active_node_data == sample_node

    plugin.on_step_end(None, "transfer_node", "success")
    assert plugin.active_node_id is None
    assert plugin.active_node_data == {}


def test_tool_timeout_boundary_interception(sample_node):
    """Verifies timeout_boundary fault short-circuits tool call."""
    node = dict(sample_node, timeout_boundary_ms=100)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert isinstance(res, dict)
    assert "short_circuit_result" in res
    err = res["short_circuit_result"]
    assert err["fault"] == "timeout_boundary"
    assert "DeadlineExceeded" in err["error"]


def test_tool_cancel_race_interception(sample_node):
    """Verifies cancel_race condition short-circuits tool execution."""
    node = dict(sample_node, cancel_at_boundary=True)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert isinstance(res, dict)
    assert "short_circuit_result" in res
    err = res["short_circuit_result"]
    assert err["fault"] == "cancel_race"
    assert "TaskCancelled" in err["error"]


def test_tool_malformed_payload_interception(sample_node):
    """Verifies raw malformed payload injection."""
    node = dict(sample_node, raw_payload_corrupted='{"unclosed_json: true')
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert isinstance(res, dict)
    assert "short_circuit_result" in res
    err = res["short_circuit_result"]
    assert err["fault"] == "malformed_payload"
    assert "InvalidJSON" in err["error"]


def test_tool_contract_violation_interception(sample_node):
    """Verifies tool contract violation mutates arguments with forbidden properties."""
    node = dict(sample_node, tool_contract_violation=True)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert isinstance(res, dict)
    assert "arguments" in res
    assert "_unexpected_forbidden_property" in res["arguments"]


def test_state_partial_commit_interception(sample_node):
    """Verifies partial_commit drops all keys after the first step."""
    node = dict(sample_node, partial_commit_simulated=True)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    state_diff = {"balance": 9500.0, "status": "completed", "ledger_id": "L123"}
    res = plugin.on_before_commit(None, state_diff)
    assert isinstance(res, dict)
    assert res.get("partial_commit_applied") is True
    assert len(res["state_diff"]) == 1
    assert "balance" in res["state_diff"]
    assert "status" not in res["state_diff"]


def test_state_stale_commit_interception(sample_node):
    """Verifies stale_commit blocks commit with optimistic lock error."""
    node = dict(sample_node, stale_commit=True, expected_base_revision="rev_1970")
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_before_commit(None, {"balance": 9000.0})
    assert isinstance(res, dict)
    assert res.get("allowed") is False
    assert "OptimisticLockError" in res.get("error", "")


def test_rollback_failure_interception(sample_node):
    """Verifies rollback_failure blocks compensating rollback execution."""
    node = dict(sample_node, rollback_handler_corrupted=True)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    allowed = plugin.on_rollback(None, {"action": "undo_wire"})
    assert allowed is False


def test_approval_interceptions_and_manager_integration(sample_node):
    """Verifies stale, mismatch, revocation, and race approval rejections in approval manager."""
    pm = PluginManager()
    plugin = RuntimeMutationPlugin()
    pm.plugins.append(plugin)

    approval_mgr = SessionApprovalManager(
        run_id="run_test",
        plugin_manager=pm,
    )

    # 1. Stale Token
    plugin.on_step_start(None, "node_1", {"approval_token": "EXPIRED_SIG_1970"})
    with pytest.raises(PermissionError, match="InvalidSignature"):
        approval_mgr.request_approval("task_1", "wire_tool", {"amount": 100})

    # 2. Transaction Mismatch
    plugin.on_step_start(
        None, "node_1", {"approval_transaction_id": "TX_MISMATCH_DIFFERENT_PAYMENT"}
    )
    with pytest.raises(PermissionError, match="ApprovalMismatch"):
        approval_mgr.request_approval("task_1", "wire_tool", {"amount": 100})

    # 3. Revocation
    plugin.on_step_start(None, "node_1", {"approval_revocation": True})
    with pytest.raises(PermissionError, match="ApprovalRevoked"):
        approval_mgr.request_approval("task_1", "wire_tool", {"amount": 100})

    # 4. Approval Race
    plugin.on_step_start(None, "node_1", {"approval_race": True})
    with pytest.raises(PermissionError, match="ApprovalRaceCondition"):
        approval_mgr.request_approval("task_1", "wire_tool", {"amount": 100})
