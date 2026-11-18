"""Faults exercised through the same durable authorization guards used on resume."""

import copy
import time
from collections.abc import Mapping

from eval_runner.approval_validation import (
    ApprovalValidationError,
    payload_hash_matches,
    validate_expiry,
)
from eval_runner.mutations.mutation_evidence import evidence_hash
from eval_runner.mutations.runtime_faults import FaultDeliveryError


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
    if fault == "approval_stale":
        try:
            validate_expiry(current)
        except ApprovalValidationError as exc:
            if exc.code != "ApprovalExpired":
                raise
        else:
            expire = getattr(store, "expire_request", None)
            if not callable(expire):
                raise FaultDeliveryError("Provider lacks durable expiry updates")
            expire(token, run_id=controller.run_id, scope=scope)
            current = store.get_request(token, scope=scope)
            if current is None or current.run_id != controller.run_id:
                raise FaultDeliveryError("Expired authorization was not durably observed")
        observed_at = time.time()
        expires_at = current.metadata.get("expires_at")
        try:
            validate_expiry(current)
        except ApprovalValidationError as exc:
            if exc.code != "ApprovalExpired":
                raise
        else:
            raise FaultDeliveryError("Authorization expiry was not observed")
        observe(
            "authorization_expiry_observed",
            expires_at=expires_at,
            observed_at=observed_at,
            request_hash=evidence_hash(current.to_dict()),
            payload_hash=current.outbound_payload_hash,
        )
    elif current.status == "PENDING":
        current = store.resolve_request(token, "APPROVED", decided_by="fault-injector", scope=scope)
    consumption = None
    if fault == "approval_replay":
        if not current.metadata.get("consumption"):
            try:
                current = consume(
                    token, run_id=controller.run_id, payload_hash=attempted_hash, scope=scope
                )
            except ApprovalValidationError as exc:
                if exc.code != "ApprovalReplayBlocked":
                    raise
                # A different authorized consumer may have spent it since our read.
                current = store.get_request(token, scope=scope)
        marker = current.metadata.get("consumption") if current is not None else None
        if (
            not isinstance(marker, Mapping)
            or marker.get("run_id") != controller.run_id
            or not payload_hash_matches(marker.get("payload_hash"), attempted_hash)
            or not isinstance(marker.get("authorization_id"), str)
            or not marker["authorization_id"]
        ):
            raise FaultDeliveryError("A bound prior consumption was not observed")
        consumption = copy.deepcopy(marker)
        observe("authorization_consumed", consumption=consumption)
    try:
        observe("authorization_attempt", attempted_at=time.time(), payload_hash=attempted_hash)
        if fault == "approval_stale" and current.status == "PENDING":
            store.resolve_request(token, "APPROVED", decided_by="fault-injector", scope=scope)
        else:
            consume(token, run_id=controller.run_id, payload_hash=attempted_hash, scope=scope)
    except ApprovalValidationError as exc:
        if exc.code != expected_code:
            raise
        latest = store.get_request(token, scope=scope)
        if latest is None:
            raise FaultDeliveryError("Rejected authorization record disappeared") from exc
        if fault == "approval_replay" and latest.metadata.get("consumption") != consumption:
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
