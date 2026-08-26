"""
eval_runner.workflow_interpreter
Deterministic token-based scheduler executing the Canonical Execution IR.

    Scenario DAG -> executable plan -> execution tokens -> node execution
        -> NODE_VERDICT -> typed edge selection -> next token wave
        -> join / retry / compensation -> WORKFLOW_VERDICT

Semantics implemented:
  - routing on the authoritative NodeVerdict.overall (never raw agent
    completion): verification/policy/parity failures enter the SAME failure
    routing as execution failures, carrying exact assertion evidence
  - typed edge selection (condition/default/error/timeout/retry/
    compensation/parallel/join) with evaluated-predicate evidence
  - NODE_FAILED != WORKFLOW_FAILED (graph failure policies)
  - bounded loops / retry edges with visitation caps
  - TRUE parallel fan-out: sibling activations of one wave execute under
    structured concurrency (asyncio.gather), with deterministic aggregation
  - generation-scoped JOIN TOKENS: a join consumes only tokens produced by
    the same branch generation, so loop iteration N can never satisfy a
    join in iteration N+1; explicit join modes all / any / n_of_m
  - real per-node wall-clock deadlines owned by the interpreter: a declared
    timeout produces a first-class TIMEOUT outcome routed through timeout
    edges (never evaluated only after an unrelated failure)
"""

from __future__ import annotations

import asyncio
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

# [P2.4] Edge-role split for join mathematics. Structural edges carry the
# plan's convergence contract; repair/exception edges (retry, compensation,
# error, timeout) route control BACK into an existing node and must never
# raise a join's required degree — counting them starved any node with a
# self-retry under the default AND-join.
_STRUCTURAL_EDGE_TYPES = frozenset(
    {
        EdgeType.SEQUENTIAL,
        EdgeType.PARALLEL,
        EdgeType.JOIN,
        EdgeType.CONDITION,
        EdgeType.DEFAULT,
    }
)
_REPAIR_EDGE_TYPES = frozenset(
    {EdgeType.RETRY, EdgeType.COMPENSATION, EdgeType.ERROR, EdgeType.TIMEOUT}
)


@dataclass
class ExecutionToken:
    """[P0-B][P2.4] Join currency: tokens move through the graph; joins consume them.

    ``epoch`` is a globally-unique fork-wave identifier minted at every edge
    fire. A join consumes ONLY tokens sharing one epoch, and firing a join
    invalidates every unused token of that epoch — a later loop wave can
    never satisfy a join left half-open by an earlier one ([P0-4]), while
    sibling branches of one fan-out always converge.

    ``branch_generation`` is retained for provenance/evidence only.
    """

    edge_id: str
    branch_generation: str
    produced_by: str
    iteration: int
    compensating: bool = False
    epoch: str = ""

    @property
    def match_key(self) -> str:
        return self.epoch


@dataclass
class ReadyItem:
    node_id: str
    iteration: int
    compensating: bool
    generation: str
    parent_exec_id: str | None
    epoch: str = ""


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
    branch_generation: str | None = None

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
            "branch_generation": self.branch_generation,
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
    branch_generation: str | None = None
    timed_out: bool = False

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
            "branch_generation": self.branch_generation,
            "timed_out": self.timed_out,
        }


@dataclass
class WorkflowOutcome:
    status: WorkflowStatus
    reason: str
    node_executions: list[NodeExecutionRecord] = field(default_factory=list)
    transitions: list[TransitionRecord] = field(default_factory=list)
    skipped_node_ids: list[str] = field(default_factory=list)
    dropped_after_cap_node_ids: list[str] = field(default_factory=list)
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
            "dropped_after_cap_node_ids": self.dropped_after_cap_node_ids,
            "failed_node_ids": self.failed_node_ids,
            "terminal_node_ids": self.terminal_node_ids,
            "steps_taken": self.steps_taken,
        }


class _SchedulerState:
    def __init__(self, plan: WorkflowPlan):
        self.plan = plan
        self.visitation_counts: dict[str, int] = {nid: 0 for nid in plan.nodes}
        self.pending_tokens: dict[str, list[ExecutionToken]] = {nid: [] for nid in plan.nodes}
        self.executed_instances: set[str] = set()
        self.failed_nodes: set[str] = set()
        self.compensated_nodes: set[str] = set()
        self.unhandled_failures: list[str] = []
        self.pending_compensations: int = 0
        # [P2.5/V11] Nodes whose activations were dropped after exhausting
        # their visitation cap — distinct from zero-visitation skips.
        self.dropped_after_cap: set[str] = set()

    def pending_compensations_increment(self) -> None:
        self.pending_compensations += 1

    def pending_compensations_decrement(self) -> None:
        self.pending_compensations = max(0, self.pending_compensations - 1)


class WorkflowInterpreter:
    """
    Executes a WorkflowPlan via a deterministic token-based scheduler.

    The DAG is the control-flow contract. Routing keys exclusively on the
    executor-reported NodeVerdict (result["status"] derived from overall);
    branch selection is driven by evaluated edge predicates; failure routing
    follows the graph's failure policy; parallel waves run concurrently and
    aggregate deterministically.
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
        self._wave_counter = 0
        self._epoch_counter = 0

    async def _default_context(self) -> dict[str, Any]:
        return {"state": {}, "result": {}, "tools_used": []}

    def _new_generation(self, producer_exec_id: str | None, kind: str) -> str:
        self._wave_counter += 1
        base = producer_exec_id or f"{self.identity.attempt_id}:entry"
        return f"{base}/{kind}{self._wave_counter}"

    def _new_epoch(self) -> str:
        """[P2.4] Mints a globally-unique join epoch (fork-wave scope)."""
        self._epoch_counter += 1
        return f"ep{self._epoch_counter}"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run(self, executor: NodeExecutor) -> tuple[list[dict[str, Any]], WorkflowOutcome]:
        state = _SchedulerState(self.plan)
        results: list[dict[str, Any]] = []
        root_gen = self._new_generation(None, "root")
        ready: list[ReadyItem] = [
            ReadyItem(nid, 1, False, root_gen, None, epoch="ep0")
            for nid in self.plan.entry_node_ids
        ]
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
                for item in ready:
                    results.append(self._aborted_result(item.node_id))
                    self._emit_node(
                        item.node_id,
                        item.iteration,
                        item.parent_exec_id,
                        "aborted",
                        generation=item.generation,
                    )
                break

            # Dequeue respecting per-node visitation caps. [P2.5/V11] Over-cap
            # items are DROPPED, never silently: each drop is recorded on the
            # scheduler state (distinct from zero-visitation skips) and emits
            # a node_dropped_over_cap event for deterministic-replay audit.
            batch: list[ReadyItem] = []
            while ready:
                cand = ready.pop(0)
                if (
                    state.visitation_counts[cand.node_id]
                    >= self.plan.nodes[cand.node_id].max_visitations
                ):
                    state.dropped_after_cap.add(cand.node_id)
                    self._emit_drop_over_cap(cand, "dequeue_cap")
                    continue
                batch.append(cand)
            if not batch:
                continue

            # [V11] Batch-level cap enforcement: sibling activations enqueued
            # before an earlier twin executed would slip past the dequeue gate
            # (stale counts) and over-run the visitation budget. Trim here,
            # deterministically, BEFORE any executor fires.
            trimmed: list[ReadyItem] = []
            per_node_slots: dict[str, int] = {}
            for cand in batch:
                remaining = (
                    self.plan.nodes[cand.node_id].max_visitations
                    - state.visitation_counts[cand.node_id]
                )
                used = per_node_slots.get(cand.node_id, 0)
                if used >= remaining:
                    state.dropped_after_cap.add(cand.node_id)
                    self._emit_drop_over_cap(cand, "batch_cap")
                    continue
                per_node_slots[cand.node_id] = used + 1
                trimmed.append(cand)
            batch = trimmed
            if not batch:
                continue

            # Deterministic pre-pass: announce every scheduled execution before
            # any of them starts (event order independent of task scheduling).
            for item in batch:
                self._emit_node(
                    item.node_id,
                    item.iteration,
                    item.parent_exec_id,
                    "running",
                    generation=item.generation,
                )

            # Structured concurrency within a wave: same-generation items run
            # concurrently; different generations run in deterministic order.
            grouped: dict[str, list[int]] = {}
            for idx, item in enumerate(batch):
                grouped.setdefault(item.generation, []).append(idx)
            batch_results: dict[int, tuple[NodeExecutionRecord, dict[str, Any], float]] = {}
            for _gen, indexes in grouped.items():
                if len(indexes) == 1:
                    i = indexes[0]
                    batch_results[i] = await self._execute_item(batch[i], executor)
                else:
                    gathered = await asyncio.gather(
                        *(self._execute_item(batch[i], executor) for i in indexes)
                    )
                    for i, packed in zip(indexes, gathered, strict=True):
                        batch_results[i] = packed

            # Deterministic post-processing in submission order.
            for idx, item in enumerate(batch):
                if steps >= budget:
                    ready.append(item)
                    continue
                steps += 1
                state.visitation_counts[item.node_id] += 1
                record, result, duration_ms = batch_results[idx]
                exec_id = record.execution_instance_id
                node_id = item.node_id
                record.status = "running"
                results.append(result)
                state.executed_instances.add(exec_id)

                node_failed = result.get("status") not in ("success", "aborted", "skipped")
                aborted = result.get("status") == "aborted"

                if aborted:
                    record.status = "aborted"
                    self.node_records.append(record)
                    self._emit_node(
                        node_id,
                        item.iteration,
                        item.parent_exec_id,
                        "aborted",
                        record=record,
                    )
                    outcome_status = WorkflowStatus.ABORTED
                    outcome_reason = "Execution cancelled during node execution"
                    halt_new_work = True
                    continue

                if node_failed:
                    record.status = "failed"
                    record.failure_class = (
                        result.get(
                            "triage_tag",
                            result.get("node_verdict", {}).get("overall")
                            if isinstance(result.get("node_verdict"), dict)
                            else None,
                        )
                        or "NODE_EXECUTION_FAILURE"
                    )
                    record.failure_reason = result.get("message", "Task constraint failed.")
                    record.timed_out = result.get("triage_tag") == "TIMEOUT"
                    self.node_records.append(record)
                    state.failed_nodes.add(node_id)
                    self._emit_node(
                        node_id,
                        item.iteration,
                        item.parent_exec_id,
                        "failed",
                        record=record,
                    )
                    next_ready, handled = await self._route_failure(node_id, item, result, state)
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
                                f"Unhandled node failure '{node_id}' "
                                f"[{record.failure_class}] under "
                                f"failure_policy={self.plan.failure_policy.value}"
                            )
                else:
                    record.status = "success"
                    self.node_records.append(record)
                    self._emit_node(
                        node_id,
                        item.iteration,
                        item.parent_exec_id,
                        "completed",
                        record=record,
                    )
                    if not item.compensating:
                        next_ready, reached_terminal = await self._route_success(
                            node_id, item, result, state
                        )
                        ready.extend(next_ready)
                        if reached_terminal:
                            terminal_ids.append(node_id)
                    else:
                        state.compensated_nodes.add(node_id)
                        state.pending_compensations_decrement()

                if halt_new_work:
                    # Fail-fast: drain everything except compensation work.
                    ready = [it for it in ready if it.compensating]

        if outcome_status == WorkflowStatus.COMPLETED and not outcome_reason:
            if state.unhandled_failures:
                outcome_status = WorkflowStatus.FAILED
                outcome_reason = (
                    f"Workflow finished with unhandled node failures: {state.unhandled_failures}"
                )
            elif not terminal_ids and self.plan.edges:
                outcome_status = WorkflowStatus.FAILED
                outcome_reason = "Workflow terminated without reaching a success terminal"
            elif getattr(state, "pending_compensations", 0) > 0:
                outcome_status = WorkflowStatus.FAILED
                outcome_reason = "Compensation path did not complete"
            else:
                outcome_reason = "All reachable terminals completed successfully"

        skipped = sorted(nid for nid, c in state.visitation_counts.items() if c == 0)
        outcome = WorkflowOutcome(
            status=outcome_status,
            reason=outcome_reason,
            node_executions=self.node_records,
            transitions=self.transitions,
            skipped_node_ids=skipped,
            dropped_after_cap_node_ids=sorted(state.dropped_after_cap),
            failed_node_ids=sorted(state.failed_nodes),
            terminal_node_ids=terminal_ids,
            steps_taken=steps,
        )
        for nid in skipped:
            self._emit_node(nid, 1, None, "skipped")
        return results, outcome

    def _emit_drop_over_cap(self, item: ReadyItem, phase: str) -> None:
        """[P2.5/V11] Over-cap scheduling drops are first-class evidence."""
        if not self.event_bus:
            return
        self.event_bus.emit(
            "node_dropped_over_cap",
            {
                "run_id": self.identity.evaluation_run_id,
                "scenario_node_id": item.node_id,
                "attempt_id": self.identity.attempt_id,
                "phase": phase,
                "compensating": bool(item.compensating),
            },
        )

    # ------------------------------------------------------------------
    # Single-node execution with interpreter-owned deadline
    # ------------------------------------------------------------------
    async def _execute_item(
        self, item: ReadyItem, executor: NodeExecutor
    ) -> tuple[NodeExecutionRecord, dict[str, Any], float]:
        node_ir = self.plan.nodes[item.node_id]
        exec_id = self.identity.execution_instance_id(item.node_id, item.iteration)
        record = NodeExecutionRecord(
            scenario_node_id=item.node_id,
            execution_instance_id=exec_id,
            parent_execution_id=item.parent_exec_id,
            iteration=item.iteration,
            status="running",
            compensating=item.compensating,
            branch_generation=item.generation,
        )
        start = time.time()
        deadline = node_ir.timeout_seconds
        try:
            if deadline is not None:
                result = await asyncio.wait_for(
                    executor(node_ir, exec_id, item.parent_exec_id), timeout=deadline
                )
            else:
                result = await executor(node_ir, exec_id, item.parent_exec_id)
        except TimeoutError:
            result = {
                "task_id": item.node_id,
                "status": "failure",
                "triage_tag": "TIMEOUT",
                "message": (
                    f"Node '{item.node_id}' exceeded its declared wall-clock "
                    f"deadline ({deadline}s). Timeout enforced by the "
                    "workflow interpreter."
                ),
                "turns_taken": 0,
                "used_tools": [],
                "conversation_history": [],
                "timed_out": True,
            }
        except Exception as exc:  # noqa: BLE001 - engine boundary
            result = {
                "task_id": item.node_id,
                "status": "failure",
                "message": f"Interpreter executor error: {exc}",
                "turns_taken": 0,
                "used_tools": [],
                "conversation_history": [],
            }
        duration_ms = round((time.time() - start) * 1000, 2)
        record.duration_ms = duration_ms
        return record, result, duration_ms

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    async def _route_success(
        self,
        node_id: str,
        item: ReadyItem,
        result: dict[str, Any],
        state: _SchedulerState,
    ) -> tuple[list[ReadyItem], bool]:
        outgoing = self.plan.outgoing(node_id)
        if not outgoing:
            return [], True

        context = await self._context_for(result)

        condition_edges = [e for e in outgoing if e.type == EdgeType.CONDITION]
        for edge in condition_edges:
            passed, observed = self._eval(edge.predicate, context)
            if passed:
                return self._fire_and_activate(
                    [edge], state, item, "predicate_matched", edge.predicate, observed
                ), False

        default_edges = [e for e in outgoing if e.type == EdgeType.DEFAULT]
        if default_edges:
            return self._fire_and_activate(
                default_edges[:1], state, item, "default_fallback"
            ), False

        loop_edges = [e for e in outgoing if e.type == EdgeType.RETRY and e.predicate is not None]
        for edge in loop_edges:
            passed, observed = self._eval(edge.predicate, context)
            if passed:
                return self._fire_and_activate(
                    [edge], state, item, "loop_iteration", edge.predicate, observed
                ), False

        fanout = [
            e for e in outgoing if e.type in (EdgeType.SEQUENTIAL, EdgeType.PARALLEL, EdgeType.JOIN)
        ]
        if fanout:
            reason_by_edge = {
                e.edge_id: ("parallel_fanout" if e.type == EdgeType.PARALLEL else "sequential")
                for e in fanout
            }
            return self._fire_and_activate(fanout, state, item, reason_by_edge), False
        return [], True

    async def _route_failure(
        self,
        node_id: str,
        item: ReadyItem,
        result: dict[str, Any],
        state: _SchedulerState,
    ) -> tuple[list[ReadyItem], bool]:
        """Routes a node failure through error/retry/compensation edges.

        [P0-2] Verification failures arrive here identically to execution
        failures: ``status="failed"`` carries triage VERIFICATION_FAILED and
        the exact failed assertion in ``message`` — recorded as transition
        evidence on the NodeExecutionRecord.

        [P0-7] A TIMEOUT triage routes through declared timeout edges FIRST;
        timeout edges are otherwise consulted last.
        """
        outgoing = self.plan.outgoing(node_id)
        context = await self._context_for(result)
        is_timeout = result.get("triage_tag") == "TIMEOUT"

        timeout_edges = [e for e in outgoing if e.type == EdgeType.TIMEOUT]
        error_edges = [e for e in outgoing if e.type == EdgeType.ERROR]

        primary = timeout_edges if is_timeout else error_edges
        secondary = error_edges if is_timeout else timeout_edges

        for edge in primary:
            if edge.predicate is not None:
                passed, observed = self._eval(edge.predicate, context)
                if not passed:
                    continue
                reason = "timeout_matched" if is_timeout else "error_handler_matched"
                return self._fire_and_activate(
                    [edge], state, item, reason, edge.predicate, observed
                ), True
            reason = "timeout_route" if is_timeout else "error_handler"
            return self._fire_and_activate([edge], state, item, reason), True

        retry_edges = [e for e in outgoing if e.type == EdgeType.RETRY]
        for edge in retry_edges:
            if state.visitation_counts[node_id] >= self.plan.nodes[node_id].max_visitations:
                continue
            if edge.predicate is not None:
                passed, observed = self._eval(edge.predicate, context)
                if not passed:
                    continue
                return self._fire_and_activate(
                    [edge], state, item, "retry_predicate_matched", edge.predicate, observed
                ), True
            return self._fire_and_activate([edge], state, item, "retry"), True

        compensation_edges = [e for e in outgoing if e.type == EdgeType.COMPENSATION]
        if compensation_edges:
            return self._fire_and_activate(
                compensation_edges, state, item, "compensation", compensating=True
            ), True

        for edge in secondary:
            if edge.predicate is None or self._eval(edge.predicate, context)[0]:
                reason = "timeout_route" if not is_timeout else "error_handler"
                return self._fire_and_activate([edge], state, item, reason), True

        return [], False

    # ------------------------------------------------------------------
    # Token production + generation-scoped join activation
    # ------------------------------------------------------------------
    def _fire_and_activate(
        self,
        edges: list[EdgeIR],
        state: _SchedulerState,
        item: ReadyItem,
        reason: str | dict[str, str],
        predicate: PredicateIR | None = None,
        observed: Any = None,
        compensating: bool = False,
    ) -> list[ReadyItem]:
        producer_exec_id = self.identity.execution_instance_id(item.node_id, item.iteration)
        # [P0-4][P2.4] Epoch semantics: tokens INHERIT the wave epoch of their
        # producing item; a multi-edge fan-out mints a FRESH epoch so its
        # siblings converge at downstream joins while other waves never mix.
        # A retried loop wave therefore re-mints exactly once per pass over
        # the fork head — cross-wave satisfaction is structurally impossible.
        lineage = item.generation
        if len(edges) > 1:
            epoch = self._new_epoch()
        else:
            epoch = item.epoch

        activated: list[ReadyItem] = []
        seen_keys: set[tuple[str, int, str]] = set()
        for edge in edges:
            edge_reason = (
                reason.get(edge.edge_id, "transition") if isinstance(reason, dict) else reason
            )
            self._fire(
                edge,
                edge_reason,
                predicate=predicate,
                observed=observed,
                producer_exec_id=producer_exec_id,
                iteration=item.iteration,
                generation=lineage,
                compensating=compensating or item.compensating,
            )
            token = ExecutionToken(
                edge_id=edge.edge_id,
                branch_generation=lineage,
                produced_by=producer_exec_id,
                iteration=item.iteration,
                compensating=compensating or item.compensating,
                epoch=epoch,
            )
            state.pending_tokens.setdefault(edge.to_node, []).append(token)
            if token.compensating:
                # A fired compensation edge is an outstanding rollback
                # obligation until its target node completes successfully.
                # Without this increment the end-of-workflow check can never
                # fire (dead branch) and a dropped/incomplete compensation
                # would silently certify as COMPLETED/PASS.
                state.pending_compensations_increment()
            for ji in self._try_join(edge.to_node, item, state):
                key = (ji.node_id, ji.iteration, ji.generation)
                if key not in seen_keys:
                    seen_keys.add(key)
                    activated.append(ji)
        return activated

    def _try_join(self, target: str, item: ReadyItem, state: _SchedulerState) -> list[ReadyItem]:
        """
        [P0-4][P0-5][P2.4] Epoch-scoped join activation.

        Structural inputs (sequential/parallel/join/condition/default) are
        grouped strictly by JOIN EPOCH: a join consumes ONLY tokens minted by
        the same fork-wave fire, and firing invalidates every unused token of
        that epoch, so late arrivals from an older wave can never satisfy (or
        inflate) a later join. Repair edges (retry/compensation/error/timeout)
        BYPASS join mathematics entirely — they re-activate the target
        directly in their own epoch and never raise the required degree.

        Modes over the STRUCTURAL in-degree: all (AND), any, n_of_m.
        """
        incoming = self.plan.incoming(target)
        if not incoming:
            return []
        structural_ids = {e.edge_id for e in incoming if e.type in _STRUCTURAL_EDGE_TYPES}
        repair_ids = {e.edge_id for e in incoming} - structural_ids

        tokens = state.pending_tokens.get(target, [])

        # --- Repair-path bypass -------------------------------------------
        # A repair arrival re-activates the target INSIDE the same wave: the
        # detour must complete under its original epoch so downstream joins
        # still converge (producer iteration skew is irrelevant by design).
        repair_hit = next((t for t in tokens if t.edge_id in repair_ids), None)
        if repair_hit is not None:
            state.pending_tokens[target] = [t for t in tokens if t is not repair_hit]
            if state.visitation_counts[target] >= self.plan.nodes[target].max_visitations:
                # [P2.5/V11] Token consumed then discarded over cap: recorded.
                state.dropped_after_cap.add(target)
                self._emit_drop_over_cap(
                    ReadyItem(target, 0, repair_hit.compensating, "", None),
                    "join_token_cap",
                )
                return []
            return [
                ReadyItem(
                    node_id=target,
                    iteration=state.visitation_counts[target] + 1,
                    compensating=repair_hit.compensating,
                    generation=repair_hit.branch_generation,
                    parent_exec_id=repair_hit.produced_by,
                    epoch=repair_hit.epoch,
                )
            ]

        # --- Epoch-scoped structural join ---------------------------------
        if not structural_ids:
            return []
        mode, n_required = self.plan.nodes[target].join_spec(structural_ids)

        by_epoch: dict[str, list[ExecutionToken]] = {}
        for t in tokens:
            if t.edge_id in structural_ids:
                by_epoch.setdefault(t.epoch, []).append(t)

        chosen_epoch: str | None = None
        consumed: list[ExecutionToken] = []
        for epoch in sorted(by_epoch):
            group = by_epoch[epoch]
            covered = {t.edge_id for t in group}
            satisfied = (
                (structural_ids <= covered)
                if mode == "all"
                else (len(covered) >= max(1, n_required))
            )
            if satisfied:
                chosen_epoch = epoch
                used_edges = (
                    set(structural_ids)
                    if mode == "all"
                    else set(sorted(covered)[: max(1, n_required)])
                )
                consumed = [t for t in group if t.edge_id in used_edges]
                break

        if chosen_epoch is None or not consumed:
            return []

        # Firing the join INVALIDATES every unused token of this epoch: the
        # wave is complete; its stragglers are evidentiary dead weight.
        state.pending_tokens[target] = [
            t
            for t in tokens
            if t.epoch != chosen_epoch  # includes consumed
        ]
        if state.visitation_counts[target] >= self.plan.nodes[target].max_visitations:
            # [P2.5/V11] Satisfied join discarded over cap: recorded.
            state.dropped_after_cap.add(target)
            self._emit_drop_over_cap(
                ReadyItem(target, 0, any(t.compensating for t in consumed), "", None),
                "join_satisfied_cap",
            )
            return []
        parent = sorted(consumed, key=lambda t: t.edge_id)[0].produced_by
        lineage = sorted(consumed, key=lambda t: t.edge_id)[0].branch_generation
        # Wave boundary ONLY at true merges (>1 token consumed): a pass-through
        # single-token join must not fork the epoch space, or every hop would.
        joined_epoch = self._new_epoch() if len(consumed) > 1 else consumed[0].epoch
        return [
            ReadyItem(
                node_id=target,
                iteration=state.visitation_counts[target] + 1,
                compensating=any(t.compensating for t in consumed),
                generation=lineage,
                parent_exec_id=parent,
                epoch=joined_epoch,
            )
        ]

    def _fire(
        self,
        edge: EdgeIR,
        reason: str,
        predicate: PredicateIR | None = None,
        observed: Any = None,
        producer_exec_id: str | None = None,
        iteration: int = 1,
        generation: str | None = None,
        compensating: bool = False,
    ) -> TransitionRecord:
        rec = TransitionRecord(
            from_node=edge.from_node,
            to_node=edge.to_node,
            selected_edge_id=edge.edge_id,
            edge_type=edge.type.value,
            transition_reason=reason,
            evaluated_predicate=predicate.to_evidence() if predicate else None,
            observed_value=observed,
            source_execution_id=producer_exec_id,
            branch_generation=generation,
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
                    "source_execution_id": producer_exec_id,
                    "branch_generation": generation,
                    "compensating": compensating,
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
            "triage_tag": result.get("triage_tag"),
            "node_verdict": result.get("node_verdict"),
        }
        # Executor-provided fields are exposed so declared transition
        # predicates (e.g. ``result.retry_again``) can route loops/retries.
        # Canonical keys above always win.
        for key, value in result.items():
            if key not in ctx["result"] and not key.startswith("_"):
                ctx["result"][key] = value
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
        generation: str | None = None,
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
            "branch_generation": generation or (record.branch_generation if record else None),
        }
        if record:
            if record.duration_ms:
                payload["duration_ms"] = record.duration_ms
            if record.failure_class:
                payload["failure_class"] = record.failure_class
            if record.failure_reason:
                payload["failure_reason"] = record.failure_reason
            payload["parent_execution_id"] = record.parent_execution_id
            payload["timed_out"] = record.timed_out
        try:
            from .events import CoreEvents

            name = CoreEvents.EXECUTION_GRAPH_NODE
        except Exception:  # noqa: BLE001
            name = "execution_graph_node"
        self.event_bus.emit(name, payload)


__all__ = [
    "ExecutionToken",
    "NodeExecutionRecord",
    "ReadyItem",
    "TransitionRecord",
    "WorkflowInterpreter",
    "WorkflowOutcome",
]
