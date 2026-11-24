"""
eval_runner.mutations.mutator_plugin
==========================
RuntimeMutationPlugin provides authoritative southbound execution interception
for workflow, environmental state, timing, and human-in-the-loop mutations.
Bridges declarative AES scenario mutations to live session and tool execution.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from ..plugins import BaseEvalPlugin

logger = logging.getLogger(__name__)


class RuntimeMutationPlugin(BaseEvalPlugin):
    """
    Southbound fault injector and mutation interceptor plugin.
    Translates declarative AES scenario mutation directives into live runtime faults
    across tool dispatch, state commits, compensating rollbacks, and approvals.
    """

    is_mandatory = True
    required_interceptor_hooks = frozenset(
        {
            "on_tool_request",
            "on_tool_execution",
            "on_tool_result",
            "on_before_commit",
            "on_approval_request",
            "on_approval_resolution",
            "on_approval_preflight",
            "on_rollback",
        }
    )

    def __init__(self, scenario: dict[str, Any] | None = None):
        self.scenario: dict[str, Any] = scenario or {}
        self._node_context: ContextVar[tuple[str | None, dict[str, Any], int]] = ContextVar(
            f"runtime_mutation_node_context_{id(self)}", default=(None, {}, 0)
        )
        self.applied_mutations: list[dict[str, Any]] = []
        self._runtime_owner = ContextVar(f"mutation_owner_{id(self)}", default=None)
        self._execution_id = ContextVar(f"mutation_execution_{id(self)}", default=None)

    @property
    def active_node_id(self) -> str | None:
        return self._node_context.get()[0]

    @property
    def active_node_data(self) -> dict[str, Any]:
        from .mutation_registry import runtime_plan

        return runtime_plan(
            self._node_context.get()[1],
            self.scenario,
            self.scenario.get("metadata"),
            self.scenario.get("failure_policy"),
        )

    @property
    def step_index(self) -> int:
        return self._node_context.get()[2]

    def before_evaluation(self, context: Any, span_context: dict[str, Any] | None = None):
        """Captures scenario data from evaluation context if not provided at init."""
        if not self.scenario and hasattr(context, "scenario_data"):
            self.scenario = getattr(context, "scenario_data", {}) or {}
        elif not self.scenario and hasattr(context, "scenario"):
            self.scenario = getattr(context, "scenario", {}) or {}

    def on_step_start(
        self,
        context: Any = None,
        node_id: str | None = None,
        node_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        """Binds active step and node definition for node-scoped mutations."""
        if not self.scenario and context is not None:
            if hasattr(context, "scenario"):
                self.scenario = getattr(context, "scenario", {}) or {}
            elif hasattr(context, "scenario_data"):
                self.scenario = getattr(context, "scenario_data", {}) or {}
        if node_id is not None:
            next_step = self.step_index + 1
            self._runtime_owner.set(kwargs.get("sandbox") or context)
            self._execution_id.set(getattr(context, "current_execution_instance_id", None))
            self._node_context.set((node_id, dict(node_data or {}), next_step))
            logger.debug(f"[RuntimeMutationPlugin] Step {next_step} start: node={node_id}")

    def on_step_end(
        self,
        context: Any = None,
        node_id: str | None = None,
        verdict: Any = None,
        **kwargs: Any,
    ):
        """Cleans up active step-scoped state."""
        if node_id is not None:
            self._node_context.set((None, {}, self.step_index))
            self._runtime_owner.set(None)
            self._execution_id.set(None)

    def on_tool_request(
        self, context: Any, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """
        Intercepts tool execution to inject timing boundaries, cancellation races,
        malformed payloads, or tool contract violations.
        """
        args = arguments or {}
        node = self.active_node_data

        # 2. Cancel Race Fault
        if node.get("cancel_at_boundary"):
            from .runtime_faults import FaultDeliveryController, FaultDeliveryError

            owner = self._runtime_owner.get()
            sandbox = getattr(owner, "sandbox", None) or owner
            controller = getattr(sandbox, "fault_controller", None)
            if not isinstance(controller, FaultDeliveryController):
                raise FaultDeliveryError("Cancellation fault requires a bound runtime controller")
            receipt = controller.cancel_at_tool_boundary(
                self.active_node_id,
                tool_name,
                self._execution_id.get(),
            )
            self.applied_mutations.append(receipt)
            return {
                "short_circuit_result": {
                    "status": "error",
                    "error": "TaskCancelled: cancellation arrived at tool execution boundary",
                    "fault": "cancel_race",
                },
                "mutation_receipt": receipt,
            }

        # 4. Tool Contract Violation
        if node.get("tool_contract_violation"):
            record = {"fault": "tool_contract", "tool": tool_name, "step": self.step_index}
            self.applied_mutations.append(record)
            mutated_args = dict(args)
            mutated_args["_unexpected_forbidden_property"] = {
                "violation": "additionalProperties_forbidden"
            }
            owner = self._runtime_owner.get()
            sandbox = getattr(owner, "sandbox", None) or owner
            sandbox.tool_faults.prepare_arguments(
                args, mutated_args, self.active_node_id, self._execution_id.get(), tool_name
            )
            return {"arguments": mutated_args}

        return True

    def on_tool_execution(self, context: Any, call_data: dict[str, Any]):
        """Select faults; the sandbox owns their execution and observations."""
        return {
            "fault_plan": {
                **self.active_node_data,
                "node_id": self.active_node_id,
                "execution_instance_id": self._execution_id.get(),
                "seed": self.scenario.get("metadata", {}).get("mutation_seed", 0),
            }
        }

    def on_before_commit(
        self, context: Any, state_diff: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """
        Intercepts world state update and transaction commits to inject partial commits,
        stale optimistic locking, or post-cancellation writes.
        """
        diff = dict(state_diff or {})
        node = self.active_node_data
        if node.get("commit_after_cancel"):
            from .runtime_faults import FaultDeliveryController, FaultDeliveryError

            controller = getattr(context, "fault_controller", None)
            if not isinstance(controller, FaultDeliveryController):
                raise FaultDeliveryError("Cancelled commit requires the actual sandbox boundary")
            return {
                "state_diff": diff,
                "fault_ticket": controller.prepare_cancelled_commit(
                    self.active_node_id,
                    context.state,
                    diff,
                    self._execution_id.get(),
                ),
            }

        # 1. Partial Commit Fault
        if node.get("partial_commit_simulated"):
            from .commit_faults import SandboxCommitBoundary
            from .runtime_faults import FaultDeliveryError

            boundary = getattr(context, "commit_boundary", None)
            if not isinstance(boundary, SandboxCommitBoundary):
                raise FaultDeliveryError("Partial commit requires the actual sandbox boundary")
            selected, ticket = boundary.prepare_partial(
                diff, self.active_node_id, self._execution_id.get()
            )
            return {"state_diff": selected, "partial_ticket": ticket}

        # 2. Stale Commit (Optimistic Lock Violation)
        if node.get("stale_commit"):
            return {"stale_commit_requested": {"node_id": self.active_node_id}}

        return True

    def on_tool_result(
        self,
        context: Any,
        tool_name: str | None = None,
        result: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | bool:
        """Corrupt an actual post-execution tool response at the delivery boundary."""
        if tool_name is None:
            tool_name = str(kwargs.get("tool", ""))
        node = self.active_node_data
        if not node.get("tool_response_corrupted"):
            return True

        if isinstance(result, dict):
            corrupted = dict(result)
            corrupted["status"] = "error"
            corrupted["error"] = "InjectedToolResponseCorruption"
            corrupted["mutation_fault"] = "tool_response_corruption"
        else:
            corrupted = {
                "status": "error",
                "error": "InjectedToolResponseCorruption",
                "original_type": type(result).__name__,
                "mutation_fault": "tool_response_corruption",
            }
        owner = self._runtime_owner.get()
        sandbox = getattr(owner, "sandbox", None) or owner
        sandbox.tool_faults.prepare_corruption(
            result, corrupted, self.active_node_id, self._execution_id.get()
        )
        return {"result": corrupted}

    def on_rollback(
        self, context: Any, compensation_action: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """
        Intercepts compensating rollback execution to simulate catastrophic rollback failures.
        """
        node = self.active_node_data
        fail_policy = self.scenario.get("failure_policy")
        fail_policy_dict = fail_policy if isinstance(fail_policy, dict) else {}
        meta_dict = (
            self.scenario.get("metadata") if isinstance(self.scenario.get("metadata"), dict) else {}
        )

        if (
            node.get("rollback_handler_corrupted")
            or fail_policy_dict.get("rollback_handler_corrupted")
            or meta_dict.get("rollback_handler_corrupted")
        ):
            record = {
                "fault": "rollback_failure",
                "action": compensation_action,
                "step": self.step_index,
            }
            self.applied_mutations.append(record)
            logger.error(
                "[RuntimeMutationPlugin] Compensating rollback handler corrupted! Aborting."
            )
            return {"runtime_fault": self._approval_fault_spec("rollback_failure", {})}

        return True

    def on_approval_request(
        self, context: Any, approval_data: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """
        Intercepts human-in-the-loop approval requests to enforce stale token reuse,
        transaction ID mismatches, revocation, or approval race conditions.
        """
        return self._intercept_approval(context, approval_data)

    def on_approval_preflight(
        self, context: Any, node_data: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """Select faults without substituting preflight messages for execution."""
        return self._intercept_approval(context, node_data)

    def _intercept_approval(
        self, context: Any, approval_data: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        from .mutation_registry import selected_faults

        data = approval_data or {}
        faults = selected_faults(
            self.active_node_data, data, self.scenario, self.scenario.get("metadata")
        )
        approvals = sorted(fault for fault in faults if fault.startswith("approval_"))
        if len(approvals) > 1:
            raise ValueError("An approval boundary requires one independently observable fault")
        if approvals:
            return {"runtime_fault": self._approval_fault_spec(approvals[0], data)}
        return True

    def _approval_fault_spec(self, fault, data):
        return {
            "fault": fault,
            "node_id": self.active_node_id or data.get("task_id"),
            "execution_instance_id": self._execution_id.get(),
        }

    def on_approval_resolution(
        self, context: Any, approval_data: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        """Apply approval faults to the real decision boundary before resume."""
        return self.on_approval_request(context, approval_data)
