"""
eval_runner.mutator_plugin
==========================
RuntimeMutationPlugin provides authoritative southbound execution interception
for workflow, environmental state, timing, and human-in-the-loop mutations.
Bridges declarative AES scenario mutations to live session and tool execution.
"""

from __future__ import annotations

import logging
from typing import Any

from .plugins import BaseEvalPlugin

logger = logging.getLogger(__name__)


class RuntimeMutationPlugin(BaseEvalPlugin):
    """
    Southbound fault injector and mutation interceptor plugin.
    Translates declarative AES scenario mutation directives into live runtime faults
    across tool dispatch, state commits, compensating rollbacks, and approvals.
    """

    def __init__(self, scenario: dict[str, Any] | None = None):
        self.scenario: dict[str, Any] = scenario or {}
        self.active_node_id: str | None = None
        self.active_node_data: dict[str, Any] = {}
        self.step_index: int = 0
        self.applied_mutations: list[dict[str, Any]] = []

    def before_evaluation(self, context: Any, span_context: dict[str, Any] | None = None):
        """Captures scenario data from evaluation context if not provided at init."""
        if not self.scenario and hasattr(context, "scenario_data"):
            self.scenario = getattr(context, "scenario_data", {}) or {}
        elif not self.scenario and hasattr(context, "scenario"):
            self.scenario = getattr(context, "scenario", {}) or {}

    def on_step_start(self, context: Any, node_id: str, node_data: dict[str, Any] | None = None):
        """Binds active step and node definition for node-scoped mutations."""
        self.active_node_id = node_id
        self.active_node_data = node_data or {}
        self.step_index += 1
        logger.debug(f"[RuntimeMutationPlugin] Step {self.step_index} start: node={node_id}")

    def on_step_end(self, context: Any, node_id: str, verdict: Any = None):
        """Cleans up active step-scoped state."""
        self.active_node_id = None
        self.active_node_data = {}

    def on_tool_request(
        self, context: Any, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """
        Intercepts tool execution to inject timing boundaries, cancellation races,
        malformed payloads, or tool contract violations.
        """
        args = arguments or {}
        node = self.active_node_data

        # 1. Timeout Boundary Fault
        if node.get("timeout_boundary_ms"):
            timeout_ms = node["timeout_boundary_ms"]
            record = {
                "fault": "timeout_boundary",
                "tool": tool_name,
                "step": self.step_index,
                "timeout_ms": timeout_ms,
            }
            self.applied_mutations.append(record)
            logger.info(f"[RuntimeMutationPlugin] Injecting timeout boundary fault on {tool_name}")
            return {
                "short_circuit_result": {
                    "status": "error",
                    "error": f"DeadlineExceeded: tool execution timed out after {timeout_ms}ms",
                    "fault": "timeout_boundary",
                }
            }

        # 2. Cancel Race Fault
        if node.get("cancel_at_boundary"):
            record = {"fault": "cancel_race", "tool": tool_name, "step": self.step_index}
            self.applied_mutations.append(record)
            logger.info(f"[RuntimeMutationPlugin] Injecting cancel race condition on {tool_name}")
            return {
                "short_circuit_result": {
                    "status": "error",
                    "error": "TaskCancelled: cancellation arrived at tool execution boundary",
                    "fault": "cancel_race",
                }
            }

        # 3. Raw Payload Corruption Fault
        if node.get("raw_payload_corrupted"):
            record = {"fault": "malformed_payload", "tool": tool_name, "step": self.step_index}
            self.applied_mutations.append(record)
            logger.info(f"[RuntimeMutationPlugin] Injecting malformed payload fault on {tool_name}")
            return {
                "short_circuit_result": {
                    "status": "error",
                    "error": "InvalidJSON: raw response payload corrupted / unclosed JSON syntax",
                    "raw_corrupted": node["raw_payload_corrupted"],
                    "fault": "malformed_payload",
                }
            }

        # 4. Tool Contract Violation
        if node.get("tool_contract_violation"):
            record = {"fault": "tool_contract", "tool": tool_name, "step": self.step_index}
            self.applied_mutations.append(record)
            mutated_args = dict(args)
            mutated_args["_unexpected_forbidden_property"] = {
                "violation": "additionalProperties_forbidden"
            }
            return {"arguments": mutated_args}

        return True

    def on_before_commit(
        self, context: Any, state_diff: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """
        Intercepts world state update and transaction commits to inject partial commits,
        stale optimistic locking, or post-cancellation writes.
        """
        diff = dict(state_diff or {})
        node = self.active_node_data

        # 1. Partial Commit Fault
        if node.get("partial_commit_simulated"):
            record = {"fault": "partial_commit", "step": self.step_index}
            self.applied_mutations.append(record)
            logger.warning("[RuntimeMutationPlugin] Injecting partial transaction commit")
            if len(diff) > 1:
                first_key = next(iter(diff))
                partial_diff = {first_key: diff[first_key]}
            else:
                partial_diff = diff
            return {
                "state_diff": partial_diff,
                "partial_commit_applied": True,
                "simulated_error": "TransactionAbortedMidway: remaining keys dropped after step 1",
            }

        # 2. Stale Commit (Optimistic Lock Violation)
        if node.get("stale_commit"):
            expected = node.get("expected_base_revision", "rev_deprecated_1970")
            record = {"fault": "stale_commit", "step": self.step_index, "expected": expected}
            self.applied_mutations.append(record)
            logger.warning("[RuntimeMutationPlugin] Rejecting stale state commit")
            return {
                "allowed": False,
                "error": f"OptimisticLockError: base revision mismatch (expected {expected})",
            }

        # 3. Commit After Cancel Fault
        if node.get("commit_after_cancel"):
            record = {"fault": "commit_after_cancel", "step": self.step_index}
            self.applied_mutations.append(record)
            logger.warning("[RuntimeMutationPlugin] Tracking commit after cancellation signal")
            return {"commit_after_cancel_tracked": True}

        return True

    def on_rollback(self, context: Any, compensation_action: dict[str, Any] | None = None) -> bool:
        """
        Intercepts compensating rollback execution to simulate catastrophic rollback failures.
        """
        node = self.active_node_data
        fail_policy = self.scenario.get("failure_policy", {})

        if node.get("rollback_handler_corrupted") or fail_policy.get("rollback_handler_corrupted"):
            record = {
                "fault": "rollback_failure",
                "action": compensation_action,
                "step": self.step_index,
            }
            self.applied_mutations.append(record)
            logger.error(
                "[RuntimeMutationPlugin] Compensating rollback handler corrupted! Aborting."
            )
            return False

        return True

    def on_approval_request(
        self, context: Any, approval_data: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """
        Intercepts human-in-the-loop approval requests to enforce stale token reuse,
        transaction ID mismatches, revocation, or approval race conditions.
        """
        node = self.active_node_data
        data = approval_data or {}

        # 1. Stale Approval Token
        if (
            node.get("approval_token") == "EXPIRED_SIG_1970"
            or data.get("approval_token") == "EXPIRED_SIG_1970"
        ):
            record = {"fault": "approval_stale", "step": self.step_index}
            self.applied_mutations.append(record)
            return {
                "allowed": False,
                "error": "InvalidSignature: approval token expired in 1970 (stale token blocked)",
            }

        # 2. Approval Transaction Mismatch
        if (
            node.get("approval_transaction_id") == "TX_MISMATCH_DIFFERENT_PAYMENT"
            or data.get("approval_transaction_id") == "TX_MISMATCH_DIFFERENT_PAYMENT"
        ):
            record = {"fault": "approval_mismatch", "step": self.step_index}
            self.applied_mutations.append(record)
            return {
                "allowed": False,
                "error": "ApprovalMismatch: approval token belongs to different transaction object",
            }

        # 3. Mid-Flight Revocation
        if node.get("approval_revocation"):
            record = {"fault": "approval_revocation", "step": self.step_index}
            self.applied_mutations.append(record)
            return {
                "allowed": False,
                "error": "ApprovalRevoked: approval token was revoked midway through execution",
            }

        # 4. Approval Race Condition
        if node.get("approval_race"):
            record = {"fault": "approval_race", "step": self.step_index}
            self.applied_mutations.append(record)
            return {
                "allowed": False,
                "error": "ApprovalRaceCondition: approval collided with boundary timeout",
            }

        return True
