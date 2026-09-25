import hashlib
import logging
import secrets
from typing import Any

import eval_runner.hitl.pending as hitl_pending
from agentv_runtime.interfaces import ApprovalRequest, ApprovalStore
from eval_runner.reference.approval_store import get_default_approval_store

logger = logging.getLogger(__name__)


class SessionApprovalManager:
    """Coordinates Human-In-The-Loop approval gates, tokens, and pause state."""

    def __init__(
        self,
        run_id: str,
        registry: hitl_pending.PendingApprovalRegistry | None = None,
        checkpoint_manager: Any | None = None,
        state_provider: Any | None = None,
        plugin_manager: Any | None = None,
        approval_store: ApprovalStore | None = None,
    ):
        self.run_id = run_id
        self.registry = registry or hitl_pending.global_registry
        self.checkpoint_manager = checkpoint_manager
        self.state_provider = state_provider
        self.plugin_manager = plugin_manager
        self._approval_store = approval_store

    @property
    def approval_store(self) -> ApprovalStore:
        if self._approval_store is None:
            self._approval_store = get_default_approval_store()
        return self._approval_store

    def request_approval(
        self,
        task_id: str,
        tool_name: str,
        params: dict[str, Any],
        timeout_seconds: int = 60,
    ) -> hitl_pending.PendingApproval:
        """
        Submits an approval request to the persistent approval registry
        with durable state snapshotting.
        """
        # Trigger on_approval_request interceptor hook
        if self.plugin_manager:
            intercept = self.plugin_manager.trigger_interceptor(
                "on_approval_request",
                self,
                {"task_id": task_id, "tool_name": tool_name, "params": params},
            )
            if intercept is False or (
                isinstance(intercept, dict) and intercept.get("allowed") is False
            ):
                err_msg = (
                    getattr(self.plugin_manager, "last_rejection_reason", None)
                    or (intercept.get("error") if isinstance(intercept, dict) else None)
                    or "Approval rejected by security policy"
                )
                raise PermissionError(err_msg)
        # Durable HITL snapshotting: persist state checkpoint before entering approval wait
        if self.checkpoint_manager:
            checkpoint_state = {
                "task_id": task_id,
                "tool_name": tool_name,
                "params": params,
                "status": "AWAITING_APPROVAL",
            }
            if callable(self.state_provider):
                try:
                    checkpoint_state.update(self.state_provider())
                except Exception as e:
                    logger.debug("Failed to extract full state snapshot for approval: %s", e)
            self.checkpoint_manager.create_checkpoint(
                checkpoint_state,
                metadata={
                    "hitl_gate": True,
                    "tool": tool_name,
                    "task_id": task_id,
                },
            )

        prompt = f"Approval required for tool '{tool_name}' with parameters: {params}"
        return self.registry.create(
            task_id=task_id,
            run_id=self.run_id,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )

    def resolve_approval(
        self,
        approval_id: str,
        action: str,
        response: str | None = None,
        resolved_by: str | None = None,
    ) -> bool:
        """Resolves an approval (approve/reject)."""
        return self.registry.resolve(
            approval_id=approval_id,
            action=action,
            response=response or "Resolved",
            resolved_by=resolved_by or "system",
        )

    def list_pending_approvals(self) -> list[hitl_pending.PendingApproval]:
        """Lists active pending approvals for this run."""
        return [i for i in self.registry.pending() if i.run_id == self.run_id]

    def create_durable_request(
        self,
        turn_index: int,
        outbound_payload_hash: str = "",
        required_role: str | None = None,
        reviewer_credentials: dict[str, Any] | None = None,
        rule_id: str | None = None,
        action_payload: dict[str, Any] | None = None,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """
        Creates a durable ApprovalRequest, snapshots state into a checkpoint with
        PAUSED_FOR_APPROVAL status, and persists the record to the ApprovalStore.
        """
        token = secrets.token_urlsafe(24)
        checkpoint_id = None
        if self.checkpoint_manager:
            checkpoint_state = {
                "turn": turn_index,
                "status": "PAUSED_FOR_APPROVAL",
                "approval_token": token,
                "action_payload": action_payload or {},
            }
            if callable(self.state_provider):
                try:
                    state_data = self.state_provider()
                    if isinstance(state_data, dict):
                        checkpoint_state.update(state_data)
                except Exception as exc:
                    logger.debug("Failed extracting state snapshot for durable approval: %s", exc)
            checkpoint_id = self.checkpoint_manager.create_checkpoint(
                checkpoint_state,
                metadata={
                    "hitl_gate": True,
                    "status": "PAUSED_FOR_APPROVAL",
                    "approval_token": token,
                    "turn": turn_index,
                    "rule_id": rule_id,
                },
            )

        if not outbound_payload_hash and action_payload:
            payload_str = str(sorted(action_payload.items()))
            outbound_payload_hash = hashlib.sha3_256(payload_str.encode("utf-8")).hexdigest()

        req = ApprovalRequest(
            approval_token=token,
            run_id=self.run_id,
            turn_index=turn_index,
            outbound_payload_hash=outbound_payload_hash,
            required_role=required_role,
            reviewer_credentials=reviewer_credentials or {},
            status="PENDING",
            rule_id=rule_id,
            checkpoint_id=checkpoint_id,
            action_payload=action_payload or {},
            prompt=prompt or f"Approval required for run '{self.run_id}' turn {turn_index}",
            metadata=metadata or {},
        )
        return self.approval_store.create_request(req)

    def resolve_durable_request(
        self,
        approval_token: str,
        decision: str,
        decided_by: str | None = None,
        decision_reason: str | None = None,
    ) -> ApprovalRequest:
        """Resolves a durable approval request in the persistent store."""
        return self.approval_store.resolve_request(
            approval_token=approval_token,
            decision=decision,
            decided_by=decided_by,
            decision_reason=decision_reason,
        )

    def get_durable_request(self, approval_token: str) -> ApprovalRequest | None:
        """Retrieves a durable approval request by token."""
        return self.approval_store.get_request(approval_token)

    def list_durable_pending(self) -> list[ApprovalRequest]:
        """Lists active pending approval requests for this run."""
        return self.approval_store.list_pending(self.run_id)
