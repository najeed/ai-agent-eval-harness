"""Golden HITL restart durability contract through ApprovalStore."""

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner.reference.approval_store import FileApprovalStore


def test_golden_hitl_restart_durability_and_token(tmp_path):
    store1 = FileApprovalStore(tmp_path / "approvals")
    request = store1.create_request(
        ApprovalRequest(
            approval_token="tok_restart_durable",
            run_id="run_100",
            turn_index=1,
            outbound_payload_hash="sha3_256:payload",
            prompt="Authorize transfer of $5000?",
        )
    )
    assert request.approval_token.startswith("tok_")

    # A new provider instance is the process-restart proof.
    store2 = FileApprovalStore(tmp_path / "approvals")
    restored = store2.get_request(request.approval_token)
    assert restored is not None
    assert restored.run_id == request.run_id
    assert restored.prompt == "Authorize transfer of $5000?"
    assert [item.approval_token for item in store2.list_pending()] == [request.approval_token]

    resolved = store2.resolve_request(
        request.approval_token,
        "APPROVED",
        decided_by="admin@org",
        decision_reason="Approved by security officer",
    )
    assert resolved.status == "APPROVED"
    assert resolved.decision_reason == "Approved by security officer"
