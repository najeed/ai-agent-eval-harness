import logging
from typing import Any

import eval_runner.hitl.pending as hitl_pending

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
    ):
        self.run_id = run_id
        self.registry = registry or hitl_pending.global_registry
        self.checkpoint_manager = checkpoint_manager
        self.state_provider = state_provider
        self.plugin_manager = plugin_manager

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
