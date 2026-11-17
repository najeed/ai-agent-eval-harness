"""Execute boundary faults and attest observations, independently of plugin selection."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from eval_runner.mutation_evidence import evidence_hash
from eval_runner.utils.path_resolver import PathResolver


class FaultDeliveryError(RuntimeError):
    """The requested fault was not established by an observed runtime operation."""


class FaultDeliveryController:
    """Run-bound cancellation, commit observations, and durable approval operations."""

    def __init__(self, run_id, event_bus, cancellation_event=None):
        self.run_id = run_id
        self.event_bus = event_bus
        self.cancellation_event = (
            cancellation_event if cancellation_event is not None else threading.Event()
        )

    def _identity(self, fault, node_id, execution_id=None):
        if (
            not isinstance(self.run_id, str)
            or not self.run_id
            or not isinstance(node_id, str)
            or not node_id
            or (execution_id is not None and not isinstance(execution_id, str))
            or self.event_bus is None
            or not callable(getattr(self.event_bus, "emit_evidence", None))
            or getattr(self.event_bus, "run_id", self.run_id) not in (None, self.run_id)
        ):
            raise FaultDeliveryError("Fault injection requires a run, node and evidence sink")
        return {
            "fault_id": uuid.uuid4().hex,
            "fault": fault,
            "run_id": self.run_id,
            "node_id": node_id,
            "execution_instance_id": execution_id or node_id,
        }

    def _observe(self, kind, identity, observation):
        evidence = {
            **identity,
            "event_id": uuid.uuid4().hex,
            "kind": kind,
            "observed_at": datetime.now(UTC).isoformat(),
            "observation": observation,
        }
        digest = evidence_hash(evidence)
        # Evidence failures propagate: an unrecorded operation cannot claim delivery.
        self.event_bus.emit_evidence(
            "runtime_fault_observation",
            {
                "run_id": self.run_id,
                "evidence": evidence,
                "evidence_hash": digest,
            },
        )
        return {"event_id": evidence["event_id"], "evidence_hash": digest}

    def _receipt(self, identity, refs, observed, *, delivery="DELIVERED"):
        if delivery not in {"DELIVERED", "NOT_DELIVERED"} or not refs:
            raise FaultDeliveryError("A delivery decision requires bound observations")
        receipt = {**identity, "delivery": delivery, "evidence_refs": refs, "observed": observed}
        receipt["receipt_hash"] = evidence_hash(receipt)
        self.event_bus.emit_evidence(
            "mutation_delivery",
            {
                "run_id": self.run_id,
                "category": "MUTATION_DELIVERY",
                "mutation_receipt": receipt,
            },
        )
        return receipt

    def cancel_at_tool_boundary(self, node_id, tool_name, execution_id=None):
        identity = self._identity("cancel_race", node_id, execution_id)
        self.cancellation_event.set()
        if not self.cancellation_event.is_set():
            raise FaultDeliveryError("Cancellation signal was not acknowledged")
        ref = self._observe(
            "cancellation_requested",
            identity,
            {
                "cancelled": True,
                "tool": tool_name,
                "tool_dispatched": False,
            },
        )
        return self._receipt(
            identity,
            [ref],
            {
                "cancelled": True,
                "tool": tool_name,
                "tool_dispatched": False,
            },
        )

    def prepare_cancelled_commit(self, node_id, state, diff, execution_id=None):
        identity = self._identity("commit_after_cancel", node_id, execution_id)
        if not diff:
            raise FaultDeliveryError("A cancelled commit requires a nonempty proposed write")
        self.cancellation_event.set()
        if not self.cancellation_event.is_set():
            raise FaultDeliveryError("Cancellation signal was not acknowledged")
        ref = self._observe("cancellation_requested", identity, {"cancelled": True})
        return {
            "identity": identity,
            "evidence_refs": [ref],
            "before_hash": evidence_hash(state),
            "diff": dict(diff),
        }

    def observe_cancelled_commit(self, ticket, after):
        if (
            not self.cancellation_event.is_set()
            or any(
                PathResolver.resolve(after, path) != value for path, value in ticket["diff"].items()
            )
            or evidence_hash(after) == ticket["before_hash"]
        ):
            raise FaultDeliveryError("Post-cancellation state change was not observed")
        observation = {
            "cancelled": True,
            "before_hash": ticket["before_hash"],
            "after_hash": evidence_hash(after),
            "diff_hash": evidence_hash(ticket["diff"]),
        }
        ref = self._observe("state_commit_observed", ticket["identity"], observation)
        return self._receipt(ticket["identity"], [*ticket["evidence_refs"], ref], observation)

    def approval_fault(self, fault, store, request, scope=None, *, node_id, execution_id=None):
        if fault not in {
            "approval_stale",
            "approval_mismatch",
            "approval_replay",
            "approval_race",
            "approval_revocation",
        }:
            raise FaultDeliveryError(f"Not an approval-boundary fault: {fault}")
        try:
            return self._execute_approval_fault(
                fault, store, request, scope, node_id=node_id, execution_id=execution_id
            )
        finally:
            # Evidence capture can fail after an injected grant. Such failure
            # must never leave the test authorization usable for business work.
            current = store.get_request(request.approval_token, scope=scope)
            if (
                current is not None
                and current.run_id == self.run_id
                and current.status == "APPROVED"
            ):
                store.revoke_request(
                    request.approval_token, decided_by="fault-cleanup", scope=scope
                )

    def _execute_approval_fault(
        self, fault, store, request, scope=None, *, node_id, execution_id=None
    ):
        if fault in {"approval_stale", "approval_mismatch", "approval_replay"}:
            from eval_runner.approval_faults import deliver_authorization_fault

            return deliver_authorization_fault(
                self, fault, store, request, scope, node_id, execution_id
            )
        if fault not in {"approval_race", "approval_revocation"}:
            raise FaultDeliveryError(f"Not an approval-boundary fault: {fault}")
        identity = self._identity(fault, node_id, execution_id)
        token = request.approval_token
        current = store.get_request(token, scope=scope)
        if current is None or current.run_id != self.run_id:
            raise FaultDeliveryError("Approval fault does not own the durable request")
        refs = [
            self._observe(
                "approval_before",
                identity,
                {
                    "approval_token": token,
                    "status": current.status,
                    "request_hash": evidence_hash(current.to_dict()),
                    "outbound_payload_hash": current.outbound_payload_hash,
                    "checkpoint_id": current.checkpoint_id,
                    "scope_digest": current.scope_digest,
                },
            )
        ]
        if fault == "approval_revocation":
            revoke = getattr(store, "revoke_request", None)
            if not callable(revoke):
                raise FaultDeliveryError("Approval provider does not support durable revocation")
            if current.status == "PENDING":
                current = store.resolve_request(
                    token, "APPROVED", decided_by="fault-injector", scope=scope
                )
            if current.status != "APPROVED":
                raise FaultDeliveryError("Revocation requires a granted approval")
            refs.append(
                self._observe(
                    "approval_granted",
                    identity,
                    {
                        "approval_token": token,
                        "status": current.status,
                        "request_hash": evidence_hash(current.to_dict()),
                    },
                )
            )
            revoked = revoke(token, decided_by="fault-injector", scope=scope)
            observed = store.get_request(token, scope=scope)
            if (
                observed is None
                or observed.status != "REJECTED"
                or not observed.metadata.get("revocation")
            ):
                raise FaultDeliveryError("Revocation was not durably observed")
            refs.append(
                self._observe(
                    "approval_revoked",
                    identity,
                    {
                        "approval_token": token,
                        "status": observed.status,
                        "request_hash": evidence_hash(observed.to_dict()),
                    },
                )
            )
            try:
                store.resolve_request(token, "APPROVED", decided_by="fault-replay", scope=scope)
            except ValueError:
                if store.get_request(token, scope=scope).status != "REJECTED":
                    raise FaultDeliveryError("Revoked approval changed during replay") from None
            else:
                raise FaultDeliveryError("Revoked approval was incorrectly reapproved")
            refs.append(
                self._observe(
                    "approval_replay_blocked",
                    identity,
                    {
                        "approval_token": token,
                        "status": revoked.status,
                        "blocked": True,
                    },
                )
            )
            result = {"approval_token": token, "status": observed.status, "replay_blocked": True}
        else:
            if current.status != "PENDING":
                raise FaultDeliveryError("Approval race requires an unresolved durable request")
            revoke = getattr(store, "revoke_request", None)
            if not callable(revoke):
                raise FaultDeliveryError(
                    "Race injection requires a provider that can withdraw its test grant"
                )
            barrier = threading.Barrier(2)

            def contender(decision):
                barrier.wait(timeout=10)
                try:
                    resolved = store.resolve_request(
                        token, decision, decided_by=f"fault-race:{decision}", scope=scope
                    )
                except ValueError:
                    latest = store.get_request(token, scope=scope)
                    if latest is None or latest.status == "PENDING":
                        raise
                    return {"decision": decision, "accepted": False}
                return {"decision": decision, "accepted": True, "status": resolved.status}

            executor = ThreadPoolExecutor(max_workers=2)
            try:
                futures = [
                    executor.submit(contender, decision) for decision in ("APPROVED", "REJECTED")
                ]
                outcomes = [future.result(timeout=15) for future in futures]
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            observed = store.get_request(token, scope=scope)
            winners = [row for row in outcomes if row["accepted"]]
            if len(winners) != 1 or observed is None or observed.status != winners[0]["decision"]:
                raise FaultDeliveryError("Approval provider did not serialize competing decisions")
            result = {"approval_token": token, "status": observed.status, "contenders": outcomes}
            refs.append(
                self._observe(
                    "approval_race_observed",
                    identity,
                    {
                        **result,
                        "request_hash": evidence_hash(observed.to_dict()),
                    },
                )
            )
            # The race tests the decision boundary, never authorizes a business
            # action. Withdraw an injected winning grant before returning control.
            if observed.status == "APPROVED":
                observed = revoke(token, decided_by="fault-race-cleanup", scope=scope)
                refs.append(
                    self._observe(
                        "approval_race_cleanup",
                        identity,
                        {
                            "approval_token": token,
                            "status": observed.status,
                            "request_hash": evidence_hash(observed.to_dict()),
                        },
                    )
                )
            result["winner"] = result["status"]
            result["status"] = observed.status
        return self._receipt(identity, refs, result)
