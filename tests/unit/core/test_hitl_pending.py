"""ApprovalStore contract regressions replacing the retired hitl.db registry."""

from datetime import UTC, datetime, timedelta

import pytest

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner.reference.approval_store import FileApprovalStore


def _request(token: str = "token-1", run_id: str = "run-1") -> ApprovalRequest:
    return ApprovalRequest(
        approval_token=token,
        run_id=run_id,
        turn_index=1,
        outbound_payload_hash="sha3_256:payload",
        prompt="Please authorize transfer",
        metadata={"task_id": "task_1"},
    )


def test_pending_approval_lifecycle(tmp_path):
    store = FileApprovalStore(tmp_path / "approvals")
    approval = store.create_request(_request())
    assert approval.metadata["task_id"] == "task_1"
    assert approval.run_id == "run-1"
    assert approval.prompt == "Please authorize transfer"
    assert approval.status == "PENDING"
    assert [item.approval_token for item in store.list_pending()] == [approval.approval_token]

    resolved = store.resolve_request(
        approval.approval_token,
        "APPROVED",
        decided_by="root-admin",
        decision_reason="Override signed by Admin-01",
    )
    assert resolved.status == "APPROVED"
    assert resolved.decision_reason == "Override signed by Admin-01"
    assert resolved.decided_by == "root-admin"
    assert store.list_pending() == []


def test_pending_approval_timeout_is_durable_rejection(tmp_path):
    store = FileApprovalStore(tmp_path / "approvals")
    request = _request("timeout", "run-timeout")
    request.created_at = datetime.now(UTC) - timedelta(seconds=2)
    store.create_request(request)
    resolved = store.resolve_request(
        request.approval_token,
        "REJECTED",
        decided_by="system_timeout",
        decision_reason="approval window expired",
    )
    assert resolved.status == "REJECTED"
    assert "approval window expired" in resolved.decision_reason


def test_approval_store_persists_across_instances(tmp_path):
    store1 = FileApprovalStore(tmp_path / "approvals")
    item = store1.create_request(_request("persist", "persist-run"))
    store2 = FileApprovalStore(tmp_path / "approvals")
    loaded = store2.get_request(item.approval_token)
    assert loaded is not None
    assert loaded.run_id == "persist-run"
    assert loaded.prompt == "Please authorize transfer"


def test_approval_request_contract_fields():
    approval = _request()
    data = approval.to_dict()
    assert data["run_id"] == "run-1"
    assert data["prompt"] == "Please authorize transfer"
    assert data["status"] == "PENDING"
    assert data["decision"] is None


def test_unknown_approval_is_not_resolvable(tmp_path):
    store = FileApprovalStore(tmp_path / "approvals")
    with pytest.raises(KeyError):
        store.resolve_request("no-such-id", "APPROVED")


def test_pending_stream_is_provider_owned(tmp_path):
    store = FileApprovalStore(tmp_path / "approvals")
    request = store.create_request(_request())
    events = list(store.stream_pending(scope=None))
    assert len(events) == 1
    assert events[0].request.approval_token == request.approval_token
