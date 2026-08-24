"""
eval_runner.workflow_interpreter
Deterministic ready-set scheduler executing the Canonical Execution IR.

Replaces the legacy topological-sort linearization:

    Scenario DAG -> executable plan -> ready-set scheduler -> node execution
        -> state transition -> edge predicate evaluation -> next ready set

Semantics implemented:
  - typed edge selection (condition/default/error/timeout/retry/compensation/
    parallel/join) with evaluated-predicate evidence
  - NODE_FAILED != WORKFLOW_FAILED (graph failure policies)
  - bounded loops / retry edges with visitation caps
  - AND-join convergence semantics
  - parallel fan-out from a completed node
  - step-budget termination guard
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .execution_ir import (
    EdgeIR,
    EdgeType,
    ExecutionIdentity,
    FailurePolicy,
    PredicateIR,
    WorkflowPlan,
    WorkflowStatus,
    evaluate_predicate,
)

NodeExecutor = Callable[[Any, str, str | None], Awaitable[dict[str, Any]]]
ContextProvider = Callable[[], Awaitable[dict[str, Any]]]


@dataclass
class TransitionRecord:
    """Evidence for one executed control-flow transition."""

    from_node: str
    to_node: str
    selected_edge_id: str
    edge_type: str
    transition_reason: str
    evaluated_predicate: dict[str, Any] | None = None
    observed_value: Any = None
    source_execution_id: str | None = None
    target_execution_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_node": self.from_node,
            "to_node": self.to_node,
            "selected_edge_id": self.selected_edge_id,
            "edge_type": self.edge_type,
            "transition_reason": self.transition_reason,
            "evaluated_predicate": self.evaluated_predicate,
            "observed_value": self.observed_value,
            "source_execution_id": self.source_execution_id,
            "target_execution_id": self.target_execution_id,
        }


@dataclass
class NodeExecutionRecord:
    scenario_node_id: str
    execution_instance_id: str
    parent_execution_id: str | None
    iteration: int
    status: str
    duration_ms: float = 0.0
    failure_class: str | None = None
    failure_reason: str | None = None
    compensating: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_node_id": self.scenario_node_id,
            "execution_instance_id": self.execution_instance_id,
            "parent_execution_id": self.parent_execution_id,
            "iteration": self.iteration,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "failure_class": self.failure_class,
            "failure_reason": self.failure_reason,
            "compensating": self.compensating,
        }


@dataclass
class WorkflowOutcome:
    status: WorkflowStatus
    reason: str
    node_executions: list[NodeExecutionRecord] = field(default_factory=list)
    transitions: list[TransitionRecord] = field(default_factory=list)
    skipped_node_ids: list[str] = field(default_factory=list)
    failed_node_ids: list[str] = field(default_factory=list)
    terminal_node_ids: list[str] = field(default_factory=list)
    steps_taken: int = 0

    @property
    def success(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "node_executions": [n.to_dict() for n in self.node_executions],
            "transitions": [t.to_dict() for t in self.transitions],
            "skipped_node_ids": self.skipped_node_ids,
            "failed_node_ids": self.failed_node_ids,
            "terminal_node_ids": self.terminal_node_ids,
            "steps_taken": self.steps_taken,
        }


class _SchedulerState:
    def __init__(self, plan: WorkflowPlan):
        self.plan = plan
        self.visitation_counts: dict[str, int] = {nid: 0 for nid in plan.nodes}
        self.fired_edges: set[str] = set()
        self.completed_incoming: dict[str, set[str]] = {nid: set() for nid in plan.nodes}
        self.executed_nodes: set[str] = set()
        self.failed_nodes: set[str] = set()
        self.compensated_nodes: set[str] = set()
        self.unhandled_failures: list[str] = []
        self.pending_compensations: int = 0
        self.last_execution_id: str | None = None
        self.last_scenario_node_id: str | None = None


class WorkflowInterpreter:
    """
    Executes a WorkflowPlan via a deterministic ready-set scheduler.

    The DAG is the control-flow contract: nodes execute only when activated by
    typed incoming transitions; branch selection is driven by evaluated edge
    predicates; failure routing follows the graph's failure policy.
    """

    def __init__(
        self,
        plan: WorkflowPlan,
        identity: ExecutionIdentity,
        event_bus: Any | None = None,
        context_provider: ContextProvider | None = None,
        should_abort: Callable[[], bool] | None = None,
    ):
        self.plan = plan
        self.identity = identity
        self.event_bus = event_bus
        self.context_provider = context_provider or self._default_context
        self.should_abort = should_abort or (lambda: False)
        self.transitions: list[TransitionRecord] = []
        self.node_records: list[NodeExecutionRecord] = []

    async def _default_context(self) -> dict[str, Any]:
        return {"state": {}, "result": {}, "tools_used": []}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run(self, executor: NodeExecutor) -> tuple[list[dict[str, Any]], WorkflowOutcome]:
        state = _SchedulerState(self.plan)
        results: list[dict[str, Any]] = []
        ready: list[tuple[str, int, bool]] = [(nid, 1, False) for nid in self.plan.entry_node_ids]
        budget = self.plan.step_budget
        steps = 0
        halt_new_work = False
        outcome_status = WorkflowStatus.COMPLETED
        outcome_reason = ""
        terminal_ids: list[str] = []

        while ready:
            if steps >= budget:
                outcome_status = WorkflowStatus.FAILED
                outcome_reason = f"Step budget exceeded ({budget} transitions)"
                break

            if self.should_abort():
                outcome_status = WorkflowStatus.ABORTED
                outcome_reason = "Execution cancelled"
                for nid, _it, _c in ready:
                    results.append(self._aborted_result(nid))
                    self._emit_node(nid, 1, None, "aborted")
                break

            node_id, iteration, compensating = ready.pop(0)
            if state.visitation_counts[node_id] >= self.plan.nodes[node_id].max_visitations:
                continue
            steps += 1
            state.visitation_counts[node_id] += 1

            exec_id = self.identity.execution_instance_id(node_id, iteration)
            parent = state.last_execution_id
            record = NodeExecutionRecord(
                scenario_node_id=node_id,
                execution_instance_id=exec_id,
                parent_execution_id=parent,
                iteration=iteration,
                status="running",
                compensating=compensating,
            )
            self._emit_node(node_id, iteration, parent, "running")

            start = time.time()
            try:
                result = await executor(self.plan.nodes[node_id], exec_id, parent)
            except Exception as exc:  # noqa: BLE001 - engine boundary
                result = {
                    "task_id": node_id,
                    "status": "failure",
                    "message": f"Interpreter executor error: {exc}",
                }
            duration_ms = round((time.time() - start) * 1000, 2)

            node_failed = result.get("status") not in ("success", "aborted", "skipped")
            aborted = result.get("status") == "aborted"

            record.duration_ms = duration_ms
            results.append(result)

            if aborted:
                record.status = "aborted"
                self.node_records.append(record)
                self._emit_node(node_id, iteration, parent, "aborted", record=record)
                outcome_status = WorkflowStatus.ABORTED
                outcome_reason = "Execution cancelled during node execution"
                break

            state.executed_nodes.add(node_id)
            state.last_execution_id = exec_id
            state.last_scenario_node_id = node_id

            if node_failed:
                record.status = "failed"
                record.failure_class = result.get("triage_tag", "NODE_EXECUTION_FAILURE")
                record.failure_reason = result.get("message", "Task constraint failed.")
                self.node_records.append(record)
                state.failed_nodes.add(node_id)
                self._emit_node(node_id, iteration, parent, "failed", record=record)
                next_ready, handled = await self._route_failure(node_id, result, state, ready)
                ready.extend(next_ready)
                if not handled:
                    state.unhandled_failures.append(node_id)
                    if self.plan.failure_policy in (
                        FailurePolicy.FAIL_FAST,
                        FailurePolicy.COMPENSATE_THEN_FAIL,
                    ):
                        halt_new_work = True
                        outcome_status = WorkflowStatus.FAILED
                        outcome_reason = (
                            f"Unhandled node failure '{node_id}' under "
                            f"failure_policy={self.plan.failure_policy.value}"
                        )
            else:
                record.status = "success"
                self.node_records.append(record)
                self._emit_node(node_id, iteration, parent, "completed", record=record)
                if not compensating:
                    next_ready, reached_terminal = await self._route_success(node_id, result, state)
                    ready.extend(next_ready)
                    if reached_terminal:
                        terminal_ids.append(node_id)
                else:
                    state.compensated_nodes.add(node_id)
                    state.pending_compensations = max(0, state.pending_compensations - 1)

            if halt_new_work and state.pending_compensations == 0:
                ready = [item for item in ready if item[2]]

        if outcome_status == WorkflowStatus.COMPLETED and not outcome_reason:
            if state.unhandled_failures:
                outcome_status = WorkflowStatus.FAILED
                outcome_reason = (
                    f"Workflow finished with unhandled node failures: {state.unhandled_failures}"
                )
            elif not terminal_ids and self.plan.edges:
                outcome_status = WorkflowStatus.FAILED
                outcome_reason = "Workflow terminated without reaching a success terminal"
            elif state.pending_compensations > 0:
                outcome_status = WorkflowStatus.FAILED
                outcome_reason = "Compensation path did not complete"
            else:
                outcome_reason = "All reachable terminals completed successfully"

        skipped = sorted(set(self.plan.nodes) - state.executed_nodes)
        outcome = WorkflowOutcome(
            status=outcome_status,
            reason=outcome_reason,
            node_executions=self.node_records,
            transitions=self.transitions,
            skipped_node_ids=skipped,
            failed_node_ids=sorted(state.failed_nodes),
            terminal_node_ids=terminal_ids,
            steps_taken=steps,
        )
        for nid in skipped:
            self._emit_node(nid, 1, None, "skipped")
        return results, outcome

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    async def _route_success(
        self, node_id: str, result: dict[str, Any], state: _SchedulerState
    ) -> tuple[list[tuple[str, int, bool]], bool]:
        outgoing = self.plan.outgoing(node_id)
        if not outgoing:
            return [], True

        context = await self._context_for(result)

        condition_edges = [e for e in outgoing if e.type == EdgeType.CONDITION]
        for edge in condition_edges:
            passed, observed = self._eval(edge.predicate, context)
            if passed:
                self._fire(edge, state, "predicate_matched", edge.predicate, observed)
                return self._activate(edge, state), False

        default_edges = [e for e in outgoing if e.type == EdgeType.DEFAULT]
        if default_edges:
            edge = default_edges[0]
            self._fire(edge, state, "default_fallback")
            return self._activate(edge, state), False

        loop_edges = [e for e in outgoing if e.type == EdgeType.RETRY and e.predicate is not None]
        for edge in loop_edges:
            passed, observed = self._eval(edge.predicate, context)
            if passed:
                self._fire(edge, state, "loop_iteration", edge.predicate, observed)
                return self._activate(edge, state), False

        fanout = [
            e for e in outgoing if e.type in (EdgeType.SEQUENTIAL, EdgeType.PARALLEL, EdgeType.JOIN)
        ]
        fired_any = False
        for edge in fanout:
            reason = "parallel_fanout" if edge.type == EdgeType.PARALLEL else "sequential"
            self._fire(edge, state, reason)
            fired_any = True
        if fired_any:
            targets: list[tuple[str, int, bool]] = []
            seen: set[str] = set()
            for edge in fanout:
                for item in self._activate(edge, state):
                    if item[0] not in seen:
                        seen.add(item[0])
                        targets.append(item)
            return targets, False
        return [], True

    async def _route_failure(
        self,
        node_id: str,
        result: dict[str, Any],
        state: _SchedulerState,
        ready: list[tuple[str, int, bool]],
    ) -> tuple[list[tuple[str, int, bool]], bool]:
        """Routes a node failure through error/retry/compensation edges.

        Returns (next_ready_items, handled). handled=True means the graph
        provided explicit failure routing, so NODE_FAILED does not imply
        WORKFLOW_FAILED.
        """
        outgoing = self.plan.outgoing(node_id)
        context = await self._context_for(result)

        error_edges = [e for e in outgoing if e.type == EdgeType.ERROR]
        for edge in error_edges:
            if edge.predicate is not None:
                passed, observed = self._eval(edge.predicate, context)
                if not passed:
                    continue
                self._fire(edge, state, "error_handler_matched", edge.predicate, observed)
            else:
                self._fire(edge, state, "error_handler")
            return self._activate(edge, state), True

        retry_edges = [e for e in outgoing if e.type == EdgeType.RETRY]
        for edge in retry_edges:
            if state.visitation_counts[node_id] >= self.plan.nodes[node_id].max_visitations:
                continue
            if edge.predicate is not None:
                passed, observed = self._eval(edge.predicate, context)
                if not passed:
                    continue
                self._fire(edge, state, "retry_predicate_matched", edge.predicate, observed)
            else:
                self._fire(edge, state, "retry")
            return self._activate(edge, state), True

        compensation_edges = [e for e in outgoing if e.type == EdgeType.COMPENSATION]
        next_items: list[tuple[str, int, bool]] = []
        for edge in compensation_edges:
            self._fire(edge, state, "compensation")
            state.pending_compensations += 1
            next_items.extend(self._activate(edge, state))
        if compensation_edges:
            return next_items, True

        timeout_edges = [e for e in outgoing if e.type == EdgeType.TIMEOUT]
        for edge in timeout_edges:
            if edge.predicate is None or self._eval(edge.predicate, context)[0]:
                self._fire(edge, state, "timeout_route")
                return self._activate(edge, state), True

        return [], False

    def _activate(self, edge: EdgeIR, state: _SchedulerState) -> list[tuple[str, int, bool]]:
        """Activates the edge target respecting join thresholds and caps."""
        target = edge.to_node
        required = self.plan.required_incoming(target)
        state.fired_edges.add(edge.edge_id)
        satisfied = required.issubset(state.fired_edges)
        if not satisfied:
            return []
        if state.visitation_counts[target] >= self.plan.nodes[target].max_visitations:
            return []
        iteration = state.visitation_counts[target] + 1
        return [(target, iteration, edge.type == EdgeType.COMPENSATION)]

    def _fire(
        self,
        edge: EdgeIR,
        state: _SchedulerState,
        reason: str,
        predicate: PredicateIR | None = None,
        observed: Any = None,
    ) -> TransitionRecord:
        rec = TransitionRecord(
            from_node=edge.from_node,
            to_node=edge.to_node,
            selected_edge_id=edge.edge_id,
            edge_type=edge.type.value,
            transition_reason=reason,
            evaluated_predicate=predicate.to_evidence() if predicate else None,
            observed_value=observed,
            source_execution_id=state.last_execution_id,
        )
        self.transitions.append(rec)
        if self.event_bus:
            self.event_bus.emit(
                "execution_graph_edge",
                {
                    "run_id": self.identity.evaluation_run_id,
                    "from_scenario_node_id": edge.from_node,
                    "to_scenario_node_id": edge.to_node,
                    "edge_type": edge.type.value,
                    "selected_edge_id": edge.edge_id,
                    "transition_reason": reason,
                    "evaluated_predicate": rec.evaluated_predicate,
                    "attempt_number": self.identity.attempt_number,
                    "attempt_id": self.identity.attempt_id,
                    "execution_mode": self.identity.execution_mode.value,
                },
            )
        return rec

    async def _context_for(self, result: dict[str, Any]) -> dict[str, Any]:
        base = await self.context_provider()
        ctx = dict(base)
        ctx["result"] = {
            "status": result.get("status"),
            "message": result.get("message"),
            "metrics": result.get("metrics", []),
            "used_tools": result.get("used_tools", []),
        }
        return ctx

    def _eval(self, predicate: PredicateIR | None, context: dict[str, Any]) -> tuple[bool, Any]:
        if predicate is None:
            return True, None
        return evaluate_predicate(predicate, context)

    def _aborted_result(self, node_id: str) -> dict[str, Any]:
        return {
            "task_id": node_id,
            "status": "aborted",
            "message": "Execution cancelled",
            "turns_taken": 0,
            "used_tools": [],
            "conversation_history": [],
        }

    def _emit_node(
        self,
        node_id: str,
        iteration: int,
        parent: str | None,
        status: str,
        record: NodeExecutionRecord | None = None,
    ) -> None:
        if not self.event_bus:
            return
        payload: dict[str, Any] = {
            "run_id": self.identity.evaluation_run_id,
            "scenario_node_id": node_id,
            "execution_instance_id": self.identity.execution_instance_id(node_id, iteration),
            "parent_execution_id": parent,
            "label": self.plan.nodes[node_id].definition.get("task_description") or node_id,
            "status": status,
            "attempt": self.identity.attempt_number,
            "attempt_id": self.identity.attempt_id,
            "iteration": iteration,
            "evaluation_run_id": self.identity.evaluation_run_id,
            "scenario_version_id": self.identity.scenario_version_id,
            "case_id": self.identity.case_id,
            "execution_mode": self.identity.execution_mode.value,
        }
        if record:
            if record.duration_ms:
                payload["duration_ms"] = record.duration_ms
            if record.failure_class:
                payload["failure_class"] = record.failure_class
            if record.failure_reason:
                payload["failure_reason"] = record.failure_reason
            payload["parent_execution_id"] = record.parent_execution_id
        try:
            from .events import CoreEvents

            name = CoreEvents.EXECUTION_GRAPH_NODE
        except Exception:  # noqa: BLE001
            name = "execution_graph_node"
        self.event_bus.emit(name, payload)


__all__ = [
    "NodeExecutionRecord",
    "TransitionRecord",
    "WorkflowInterpreter",
    "WorkflowOutcome",
]
