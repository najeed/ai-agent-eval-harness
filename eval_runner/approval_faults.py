"""Faults exercised through the same durable authorization guards used on resume."""

import time

from eval_runner.approval_validation import ApprovalValidationError
from eval_runner.mutation_evidence import evidence_hash
from eval_runner.runtime_faults import FaultDeliveryError


def deliver_authorization_fault(controller, fault, store, request, scope, node, execution):
    identity = controller._identity(fault, node, execution)
    token = request.approval_token
    current = store.get_request(token, scope=scope)
    if current is None or current.run_id != controller.run_id:
        raise FaultDeliveryError("Authorization fault does not own the durable request")
    refs = []

    def observe(kind, **values):
        row = {"approval_token": token, **values}
        refs.append(controller._observe(kind, identity, row))
        return row

    observe(
        "authorization_request",
        request_hash=evidence_hash(current.to_dict()),
        expires_at=current.metadata.get("expires_at"),
        payload_hash=current.outbound_payload_hash,
    )
    consume = getattr(store, "consume_request", None)
    revoke = getattr(store, "revoke_request", None)
    if not callable(consume) or not callable(revoke):
        raise FaultDeliveryError("Provider lacks atomic consumption or revocation")
    expected_code = {
        "approval_stale": "ApprovalExpired",
        "approval_mismatch": "ApprovalPayloadMismatch",
        "approval_replay": "ApprovalReplayBlocked",
    }[fault]
    attempted_hash = current.outbound_payload_hash
    if fault == "approval_mismatch":
        attempted_hash = evidence_hash({"different_action": current.action_payload})
    try:
        if fault != "approval_stale" and current.status == "PENDING":
            current = store.resolve_request(
                token, "APPROVED", decided_by="fault-injector", scope=scope
            )
        if fault == "approval_replay":
            spent = consume(
                token, run_id=controller.run_id, payload_hash=attempted_hash, scope=scope
            )
            observe("authorization_consumed", consumption=spent.metadata.get("consumption"))
        observe("authorization_attempt", attempted_at=time.time(), payload_hash=attempted_hash)
        if fault == "approval_stale" and current.status == "PENDING":
            store.resolve_request(token, "APPROVED", decided_by="fault-injector", scope=scope)
        else:
            consume(token, run_id=controller.run_id, payload_hash=attempted_hash, scope=scope)
    except ApprovalValidationError as exc:
        if exc.code != expected_code:
            raise
        latest = store.get_request(token, scope=scope)
        if fault == "approval_replay" and latest.metadata.get("consumption") != spent.metadata.get(
            "consumption"
        ):
            raise FaultDeliveryError("Replay changed the spent authorization") from exc
        observed = observe(
            "authorization_rejected",
            code=exc.code,
            blocked=True,
            request_hash=evidence_hash(latest.to_dict()),
        )
    else:
        raise FaultDeliveryError("Invalid authorization unexpectedly accepted")
    withdrawn = revoke(token, decided_by="fault-cleanup", scope=scope)
    observe("authorization_cleanup", status=withdrawn.status)
    return controller._receipt(identity, refs, observed)
