"""
eval_runner.session_components.approval_manager
Decomposed Session Component: SessionApprovalManager
"""

from typing import Any

import eval_runner.hitl.pending as hitl_pending


class SessionApprovalManager:
    """Coordinates Human-In-The-Loop approval gates, tokens, and pause state."""

    def __init__(self, run_id: str, registry: hitl_pending.PendingApprovalRegistry | None = None):
        self.run_id = run_id
        self.registry = registry or hitl_pending.global_registry

    def request_approval(
        self,
        task_id: str,
        tool_name: str,
        params: dict[str, Any],
        timeout_seconds: int = 60,
    ) -> hitl_pending.PendingApproval:
        """Submits an approval request to the persistent approval registry."""
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
