"""
eval_runner.execution_ir
Canonical Execution IR (v2.0.0).

The single authoritative contract between scenario composition and the engine:

    Scenario Definition -> Schema Validation -> Normalized Execution IR
        -> Deterministic Workflow Interpreter -> Observed Execution Events
        -> State Transition Model -> Assertion / Policy Evaluation
        -> Evidence Graph -> Verification Decision

The DAG is the control-flow contract. Every edge is executable and typed:
condition / default / error / timeout / retry / compensation / parallel / join.

Every execution produces the immutable join model:
    evaluation_run_id + scenario_version_id + case_id + attempt_id
        + attempt_number + scenario_node_id + execution_instance_id
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agentv_runtime.versions import EXECUTION_IR_VERSION  # [F1] single source

DEFAULT_MAX_NODE_VISITATIONS = 3
DEFAULT_STEP_BUDGET_MULTIPLIER = 8
MIN_STEP_BUDGET = 64


class ExecutionMode(StrEnum):
    """Explicit execution truth mode. Simulation must never masquerade as live."""

    SIMULATED = "simulated"
    RECORD_REPLAY = "record_replay"
    LIVE = "live"
    HYBRID = "hybrid"


class EdgeType(StrEnum):
    """Executable edge semantics in the canonical IR."""

    SEQUENTIAL = "sequential"
    CONDITION = "condition"
    DEFAULT = "default"
    ERROR = "error"
    TIMEOUT = "timeout"
    RETRY = "retry"
    COMPENSATION = "compensation"
    PARALLEL = "parallel"
    JOIN = "join"


class FailurePolicy(StrEnum):
    """
    Graph-level termination policy. NODE_FAILED != WORKFLOW_FAILED.
    Workflow termination is determined by this policy plus reachable terminals.
    """

    FAIL_FAST = "fail_fast"
    CONTINUE_INDEPENDENT = "continue_independent"
    COMPENSATE_THEN_FAIL = "compensate_then_fail"
    BEST_EFFORT = "best_effort"


class WorkflowStatus(StrEnum):
    """Terminal workflow verdicts produced by the interpreter."""

    COMPLETED = "workflow_completed"
    FAILED = "workflow_failed"
    ABORTED = "workflow_aborted"


class NodeVerdict:
    """
    [P0-A] The ONE authoritative node verdict.

    Nothing downstream may infer success from a lower-level signal: the
    workflow interpreter routes on ``overall`` ONLY, and ``overall`` is
    ``success`` iff every required oracle passed:

        EXECUTION_RESULT -> OBSERVED_STATE -> ASSERTION_RESULTS
            -> POLICY_RESULT -> NODE_VERDICT -> EDGE_SELECTION -> WORKFLOW_VERDICT

    Components:
      execution    : success | failed | aborted        (agent action outcome)
      verification : pass | fail | invalid | not_applicable   (oracle authority)
                     Typed oracle outcomes: PASS | FAIL | INVALID | NOT_APPLICABLE
      policy       : pass | denied | not_applicable    (tool authorization)
      parity       : pass | fail | not_applicable      (state transition proof)
    """

    def __init__(
        self,
        execution: str,
        verification: str,
        policy: str,
        parity: str,
        failed_assertion: dict[str, Any] | None = None,
    ):
        self.execution = execution
        self.verification = verification
        self.policy = policy
        self.parity = parity
        self.failed_assertion = failed_assertion

    @property
    def overall(self) -> str:
        if self.execution != "success":
            return "execution_failed"
        if self.verification == "fail":
            return "verification_failed"
        if self.verification == "invalid":
            return "evaluation_invalid"
        if self.policy == "denied":
            return "policy_denied"
        if self.parity == "fail":
            return "parity_failed"
        return "success"

    @property
    def success(self) -> bool:
        return self.overall == "success"

    def to_dict(self) -> dict[str, Any]:
        d = {
            "execution": self.execution,
            "verification": self.verification,
            "policy": self.policy,
            "parity": self.parity,
            "overall": self.overall,
        }
        if self.failed_assertion is not None:
            d["failed_assertion"] = self.failed_assertion
        return d


class PlanValidationError(ValueError):
    """Raised when a scenario workflow cannot be normalized into a valid plan."""


@dataclass(frozen=True)
class ExecutionIdentity:
    """
    First-class immutable join model for GUI, artifacts, traces, and CI.
    """

    evaluation_run_id: str
    scenario_version_id: str
    case_id: str
    attempt_id: str
    attempt_number: int
    execution_mode: ExecutionMode = ExecutionMode.SIMULATED

    @staticmethod
    def new_attempt_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def scenario_version_hash(scenario: dict[str, Any]) -> str:
        """
        Canonical evidentiary identity of the scenario revision.

        Delegates to the single authoritative implementation
        (`agentv_runtime.manifest.compute_scenario_hash`) so the runtime never
        maintains a second hashing dialect: full SHA3-256 digest in
        ``sha3_256:<hex>`` form, never truncated.
        """
        from agentv_runtime.manifest import compute_scenario_hash

        return compute_scenario_hash(scenario)

    def execution_instance_id(self, scenario_node_id: str, iteration: int = 1) -> str:
        base = f"{scenario_node_id}:attempt:{self.attempt_number}"
        return base if iteration <= 1 else f"{base}#it{iteration}"


@dataclass(frozen=True)
class PredicateIR:
    """Executable edge predicate with structured comparison operators."""

    op: str = "truthy"
    path: str | None = None
    value: Any = None
    clauses: tuple[PredicateIR, ...] = ()
    logic: str = "all"

    def to_evidence(self) -> dict[str, Any]:
        if self.clauses:
            return {
                "logic": self.logic,
                "clauses": [c.to_evidence() for c in self.clauses],
            }
        return {"op": self.op, "path": self.path, "value": self.value}


@dataclass(frozen=True)
class EdgeIR:
    """A typed, executable transition between two scenario nodes."""

    edge_id: str
    from_node: str
    to_node: str
    type: EdgeType = EdgeType.SEQUENTIAL
    predicate: PredicateIR | None = None
    priority: int = 100
    declaration_index: int = 0

    @property
    def is_conditional(self) -> bool:
        return self.type in (EdgeType.CONDITION, EdgeType.ERROR, EdgeType.TIMEOUT)

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (self.priority, self.declaration_index, self.edge_id)


@dataclass(frozen=True)
class NodeIR:
    """A normalized scenario node."""

    node_id: str
    definition: dict[str, Any] = field(default_factory=dict)
    is_entry: bool = False

    @property
    def max_visitations(self) -> int:
        raw = self.definition.get("max_visitations")
        try:
            return max(1, int(raw)) if raw is not None else DEFAULT_MAX_NODE_VISITATIONS
        except (TypeError, ValueError):
            return DEFAULT_MAX_NODE_VISITATIONS

    @property
    def join_threshold(self) -> int | None:
        raw = self.definition.get("join_threshold")
        if raw is None:
            return None
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return None

    @property
    def timeout_seconds(self) -> float | None:
        """[P0-7] Per-node wall-clock deadline owned by the interpreter."""
        raw = self.definition.get("timeout")
        if raw is None:
            return None
        try:
            v = float(raw)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    def join_spec(self, incoming_edge_ids: set[str]) -> tuple[str, int]:
        """
        [P0-5] Explicit join semantics: mode ∈ {all, any, n_of_m}.

        Declared via node ``join``: ``"any" | "all" | {"mode": "...", "n": k}``.
        Legacy scalar ``join_threshold`` compiles to n_of_m over ALL M incoming
        edges (never "first N by list order"). Defaults to AND-join (all).
        """
        raw = self.definition.get("join")
        indegree = len(incoming_edge_ids)
        mode, n = "all", indegree
        if isinstance(raw, str):
            mode = raw.strip().lower()
        elif isinstance(raw, dict):
            mode = str(raw.get("mode", "all")).strip().lower()
            try:
                n = int(raw.get("n", indegree))
            except (TypeError, ValueError):
                raise PlanValidationError(
                    f"Node '{self.node_id}': join.n must be an integer"
                ) from None
        elif self.join_threshold is not None:
            mode, n = "n_of_m", self.join_threshold
        if mode not in ("all", "any", "n_of_m"):
            raise PlanValidationError(
                f"Node '{self.node_id}': unknown join mode '{mode}' (valid: all | any | n_of_m)"
            )
        if mode == "all":
            n = indegree
        elif mode == "any":
            n = 1
        # [P0-5] n_of_m is intentionally NOT clamped to indegree here: an
        # unsatisfiable declaration (n > M) is a plan-validation error, never
        # a silently weakened join.
        return mode, max(0, n)


class OracleRequiredness(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    INFORMATIONAL = "INFORMATIONAL"


@dataclass
class OracleResult:
    """
    Authoritative evaluation outcome for a single compiled oracle assertion.
    """

    oracle_id: str
    scenario_node_id: str
    resolver: str
    requiredness: str = "REQUIRED"
    outcome: str = "NOT_EVALUATED"
    expected: Any = None
    observed: Any = None
    evidence_refs: list[str] = field(default_factory=list)
    error: str | None = None
    resolver_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "oracle_id": self.oracle_id,
            "scenario_node_id": self.scenario_node_id,
            "resolver": self.resolver,
            "requiredness": self.requiredness,
            "outcome": self.outcome,
            "expected": self.expected,
            "observed": self.observed,
            "evidence_refs": self.evidence_refs,
            "error": self.error,
            "resolver_version": self.resolver_version,
        }


@dataclass
class CompiledOracle:
    """
    [P2.6] Authoritative compiled oracle assertion.
    Every declared assertion carries an explicit resolver, evidence source,
    requiredness, and expected type.
    """

    oracle_id: str
    scenario_node_id: str
    source_type: str  # "success_criteria" | "state_hygiene" | "expected_outcome"
    resolver: str  # "metrics_calculator" | "state_hygiene" | "state_parity"
    evidence_source: str
    required: bool = True
    requiredness: str = "REQUIRED"
    expected_type: str = "any"
    definition: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "oracle_id": self.oracle_id,
            "scenario_node_id": self.scenario_node_id,
            "source_type": self.source_type,
            "resolver": self.resolver,
            "evidence_source": self.evidence_source,
            "required": self.required,
            "requiredness": self.requiredness,
            "expected_type": self.expected_type,
        }


@dataclass
class CompiledEvaluationPlan:
    """
    [P2.6] Authoritative compiled evaluation inventory across the entire scenario.
    """

    oracles: dict[str, CompiledOracle] = field(default_factory=dict)
    node_oracles: dict[str, list[CompiledOracle]] = field(default_factory=dict)

    def required_oracles_for_node(self, node_id: str) -> list[CompiledOracle]:
        return [o for o in self.node_oracles.get(node_id, []) if o.required]

    def all_required_oracles(self) -> list[CompiledOracle]:
        return [o for o in self.oracles.values() if o.required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_oracles": len(self.oracles),
            "required_oracles": len(self.all_required_oracles()),
            "oracles": {k: v.to_dict() for k, v in self.oracles.items()},
        }


@dataclass
class WorkflowPlan:
    """
    Normalized, validated execution plan compiled from the scenario DAG.
    Deterministic: iteration order is derived from declaration order.
    """

    nodes: dict[str, NodeIR]
    edges: list[EdgeIR]
    entry_node_ids: list[str]
    failure_policy: FailurePolicy = FailurePolicy.FAIL_FAST
    ir_version: str = EXECUTION_IR_VERSION
    legacy_linearized: bool = False
    evaluation_plan: CompiledEvaluationPlan | None = None

    def outgoing(self, node_id: str) -> list[EdgeIR]:
        return sorted((e for e in self.edges if e.from_node == node_id), key=lambda e: e.sort_key)

    def incoming(self, node_id: str) -> list[EdgeIR]:
        return [e for e in self.edges if e.to_node == node_id]

    def required_incoming(self, node_id: str) -> set[str]:
        """
        Candidate incoming edge IDs for join activation of node.

        [P0-5] The activation decision itself is generation-scoped and
        threshold-aware (see WorkflowInterpreter._activate); this set is the
        candidate pool over ALL incoming edges, independent of list order.
        """
        return {e.edge_id for e in self.incoming(node_id)}

    @property
    def step_budget(self) -> int:
        return max(
            MIN_STEP_BUDGET,
            len(self.nodes) * DEFAULT_STEP_BUDGET_MULTIPLIER * DEFAULT_MAX_NODE_VISITATIONS,
        )


def derive_oracle_id(
    kind: str,
    node_id: str,
    entry: dict[str, Any],
    idx: int = 0,
) -> str:
    """
    Derives a canonical, stable oracle ID for success criteria, state hygiene, or expected outcomes.
    Acts as the single source of truth across compile-time IR validation and runtime reconciliation.
    """
    explicit = entry.get("id") or entry.get("oracle_id")
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()

    if kind in ("sc", "success_criteria"):
        val = entry.get("metric")
        suffix = str(val) if val is not None and str(val).strip() else str(idx)
        return f"{node_id}:sc:{suffix}"
    if kind in ("hygiene", "state_hygiene", "sh"):
        val = entry.get("path")
        suffix = str(val) if val is not None and str(val).strip() else str(idx)
        return f"{node_id}:hygiene:{suffix}"
    if kind in ("parity", "expected_outcome", "eo"):
        val = entry.get("target")
        suffix = str(val) if val is not None and str(val).strip() else str(idx)
        return f"{node_id}:parity:{suffix}"

    return f"{node_id}:{kind}:{idx}"


def compile_evaluation_plan(
    scenario: dict[str, Any], plan: WorkflowPlan | None = None
) -> CompiledEvaluationPlan:
    """
    Compiles an authoritative evaluation plan containing every assertion, its
    resolver, evidence source, requiredness, and expected type.
    Fails validation on duplicate oracle IDs or malformed assertion entries.
    """
    eval_plan = CompiledEvaluationPlan()
    nodes_to_inspect: dict[str, NodeIR] = {}
    if plan is not None:
        nodes_to_inspect = plan.nodes
    else:
        wf = scenario.get("workflow", {})
        nodes_raw = (
            wf if isinstance(wf, list) else wf.get("nodes", []) if isinstance(wf, dict) else []
        )
        for n in nodes_raw:
            if isinstance(n, dict) and "id" in n:
                nid = str(n["id"])
                nodes_to_inspect[nid] = NodeIR(node_id=nid, definition=copy.deepcopy(n))

    for node_id, node in nodes_to_inspect.items():
        definition = node.definition
        criteria = definition.get("success_criteria") or []
        if isinstance(criteria, list):
            for idx, c in enumerate(criteria):
                if not isinstance(c, dict):
                    raise PlanValidationError(
                        f"Malformed success_criteria on node '{node_id}': "
                        f"expected dict, got {type(c).__name__}"
                    )
                oid = derive_oracle_id("sc", node_id, c, idx)
                if oid in eval_plan.oracles:
                    raise PlanValidationError(
                        f"Duplicate oracle_id '{oid}' declared in evaluation plan. "
                        "Oracle identifiers must be unique across all assertions."
                    )
                target = str(
                    c.get("target")
                    or c.get("property")
                    or c.get("name")
                    or c.get("metric")
                    or "metric"
                )
                req = bool(c.get("required", True))
                req_level = str(
                    c.get("requiredness") or ("REQUIRED" if req else "OPTIONAL")
                ).upper()
                compiled = CompiledOracle(
                    oracle_id=oid,
                    scenario_node_id=node_id,
                    source_type="success_criteria",
                    resolver="metrics_calculator",
                    evidence_source=target,
                    required=req and req_level == "REQUIRED",
                    requiredness=req_level,
                    expected_type=str(c.get("type", "metric")),
                    definition=copy.deepcopy(c),
                )
                eval_plan.oracles[oid] = compiled
                eval_plan.node_oracles.setdefault(node_id, []).append(compiled)

        hygiene = definition.get("state_hygiene")
        if isinstance(hygiene, dict):
            rules = hygiene.get("rules") or []
            if isinstance(rules, list):
                for idx, r in enumerate(rules):
                    if not isinstance(r, dict):
                        raise PlanValidationError(
                            f"Malformed state_hygiene rule on node '{node_id}': "
                            f"expected dict, got {type(r).__name__}"
                        )
                    oid = derive_oracle_id("hygiene", node_id, r, idx)
                    if oid in eval_plan.oracles:
                        raise PlanValidationError(
                            f"Duplicate oracle_id '{oid}' declared in evaluation plan. "
                            "Oracle identifiers must be unique across all assertions."
                        )
                    path = str(r.get("path") or r.get("target") or "state")
                    req = bool(r.get("required", True))
                    req_level = str(
                        r.get("requiredness") or ("REQUIRED" if req else "OPTIONAL")
                    ).upper()
                    compiled = CompiledOracle(
                        oracle_id=oid,
                        scenario_node_id=node_id,
                        source_type="state_hygiene",
                        resolver="state_hygiene",
                        evidence_source=path,
                        required=req and req_level == "REQUIRED",
                        requiredness=req_level,
                        expected_type=str(r.get("type", "hygiene_rule")),
                        definition=copy.deepcopy(r),
                    )
                    eval_plan.oracles[oid] = compiled
                    eval_plan.node_oracles.setdefault(node_id, []).append(compiled)

        expected_outcome = definition.get("expected_outcome") or []
        if isinstance(expected_outcome, list):
            for idx, o in enumerate(expected_outcome):
                if not isinstance(o, dict):
                    raise PlanValidationError(
                        f"Malformed expected_outcome on node '{node_id}': "
                        f"expected dict, got {type(o).__name__}"
                    )
                oid = derive_oracle_id("parity", node_id, o, idx)
                if oid in eval_plan.oracles:
                    raise PlanValidationError(
                        f"Duplicate oracle_id '{oid}' declared in evaluation plan. "
                        "Oracle identifiers must be unique across all assertions."
                    )

                target = str(o.get("target") or o.get("property") or "state")
                req = bool(o.get("required", True))
                req_level = str(
                    o.get("requiredness") or ("REQUIRED" if req else "OPTIONAL")
                ).upper()
                compiled = CompiledOracle(
                    oracle_id=oid,
                    scenario_node_id=node_id,
                    source_type="expected_outcome",
                    resolver="state_parity",
                    evidence_source=target,
                    required=req and req_level == "REQUIRED",
                    requiredness=req_level,
                    expected_type=str(o.get("mode", "exact")),
                    definition=copy.deepcopy(o),
                )
                eval_plan.oracles[oid] = compiled
                eval_plan.node_oracles.setdefault(node_id, []).append(compiled)

    return eval_plan


def _normalize_predicate(raw: Any) -> PredicateIR:
    if raw is None:
        return PredicateIR(op="truthy")
    if isinstance(raw, bool):
        return PredicateIR(op="eq", value=raw)
    if isinstance(raw, str):
        return PredicateIR(op="regex", value=raw)
    if isinstance(raw, dict):
        if "all" in raw or "any" in raw:
            clauses_raw = raw.get("all") or raw.get("any") or []
            if not isinstance(clauses_raw, list):
                raise PlanValidationError("predicate all/any must contain a list of clauses")
            return PredicateIR(
                op="compound",
                logic="all" if "all" in raw else "any",
                clauses=tuple(_normalize_predicate(c) for c in clauses_raw),
            )
        op = str(raw.get("op", "eq"))
        path = raw.get("path") or raw.get("target")
        return PredicateIR(op=op, path=path, value=raw.get("value"))
    raise PlanValidationError(f"Unsupported predicate form: {type(raw).__name__}")


_EDGE_TYPE_ALIASES: dict[str, EdgeType] = {
    "sequential": EdgeType.SEQUENTIAL,
    "sequence": EdgeType.SEQUENTIAL,
    "condition": EdgeType.CONDITION,
    "conditional": EdgeType.CONDITION,
    "default": EdgeType.DEFAULT,
    "fallback": EdgeType.DEFAULT,
    "error": EdgeType.ERROR,
    "on_error": EdgeType.ERROR,
    "exception": EdgeType.ERROR,
    "timeout": EdgeType.TIMEOUT,
    "retry": EdgeType.RETRY,
    "loop": EdgeType.RETRY,
    "iteration": EdgeType.RETRY,
    "compensation": EdgeType.COMPENSATION,
    "compensate": EdgeType.COMPENSATION,
    "undo": EdgeType.COMPENSATION,
    "parallel": EdgeType.PARALLEL,
    "fork": EdgeType.PARALLEL,
    "join": EdgeType.JOIN,
}


def normalize_edge_type(raw: Any) -> EdgeType:
    if not raw:
        return EdgeType.SEQUENTIAL
    key = str(raw).strip().lower()
    if key not in _EDGE_TYPE_ALIASES:
        raise PlanValidationError(
            f"Unknown edge type '{raw}'. Executable types: {sorted({t.value for t in EdgeType})}"
        )
    return _EDGE_TYPE_ALIASES[key]


def compile_workflow(scenario: dict[str, Any]) -> WorkflowPlan:
    """
    Compiles the scenario workflow section into a validated WorkflowPlan.

    Legacy compatibility: list-form workflows (or dict workflows without edges)
    are compiled as an explicit linear chain in declared order, preserving
    historical execute-every-node-once semantics while making the control flow
    an explicit typed graph.
    """
    workflow = scenario.get("workflow", {})
    nodes_raw: list[dict[str, Any]] = []
    edges_raw: list[dict[str, Any]] = []
    legacy_linearized = False

    if isinstance(workflow, list):
        nodes_raw = [n for n in workflow if isinstance(n, dict) and "id" in n]
        edges_raw = []
        legacy_linearized = True
    elif isinstance(workflow, dict):
        nodes_raw = [n for n in workflow.get("nodes", []) if isinstance(n, dict) and "id" in n]
        edges_raw = [e for e in workflow.get("edges", []) if isinstance(e, dict)]
    elif workflow:
        raise PlanValidationError(f"workflow must be a dict or list, got {type(workflow).__name__}")

    # Legacy compatibility: no explicit edges => explicit linear chain in
    # declared order (execute-every-node-once semantics, now as a typed graph).
    if not edges_raw and len(nodes_raw) > 1:
        edges_raw = [
            {"from": a["id"], "to": b["id"]} for a, b in zip(nodes_raw, nodes_raw[1:], strict=False)
        ]
        legacy_linearized = True

    if not nodes_raw:
        raise PlanValidationError("Workflow contains no executable nodes")

    nodes: dict[str, NodeIR] = {}
    declared_order: list[str] = []
    for _idx, n in enumerate(nodes_raw):
        nid = str(n["id"])
        if nid in nodes:
            raise PlanValidationError(f"Duplicate workflow node id: '{nid}'")
        # [P0-11] is_entry is assigned ONLY by explicit entry resolution below.
        nodes[nid] = NodeIR(node_id=nid, definition=copy.deepcopy(n), is_entry=False)
        declared_order.append(nid)

    edges: list[EdgeIR] = []
    for idx, e in enumerate(edges_raw):
        src = e.get("source") or e.get("from")
        trg = e.get("target") or e.get("to")
        if not src or not trg:
            raise PlanValidationError(f"Edge #{idx} missing endpoint: {e}")
        src, trg = str(src), str(trg)
        if src not in nodes:
            raise PlanValidationError(f"Edge references unknown source node: '{src}'")
        if trg not in nodes:
            raise PlanValidationError(f"Edge references unknown target node: '{trg}'")
        raw_predicate: Any = None
        for key in ("predicate", "condition", "when"):
            if key in e:
                raw_predicate = e[key]
                break
        has_predicate = raw_predicate is not None

        declared_type = e.get("type")
        if not declared_type:
            untyped_same_src = [
                x
                for x in edges_raw
                if (x.get("source") or x.get("from")) == src
                and not x.get("type")
                and not any(k in x for k in ("predicate", "condition", "when"))
            ]
            if len(untyped_same_src) > 1 and not has_predicate:
                etype = EdgeType.PARALLEL
            else:
                etype = EdgeType.SEQUENTIAL
        else:
            etype = normalize_edge_type(declared_type)

        if etype == EdgeType.SEQUENTIAL and has_predicate:
            etype = EdgeType.CONDITION
        predicate = _normalize_predicate(raw_predicate) if has_predicate else None
        try:
            priority = int(e.get("priority", 100))
        except (TypeError, ValueError):
            priority = 100
        edges.append(
            EdgeIR(
                edge_id=e.get("id") or f"e{idx}:{src}->{trg}",
                from_node=src,
                to_node=trg,
                type=etype,
                predicate=predicate,
                priority=priority,
                declaration_index=idx,
            )
        )

    # [P0-11] Explicit entry semantics. Declaration order must NEVER decide
    # control flow: the entry set is either declared (workflow.entry_nodes or
    # node-level entry: true) or derived canonically as the unique
    # zero-indegree source. Ambiguous multi-source graphs are rejected.
    declared_entries: list[str] | None = None
    if isinstance(workflow, dict):
        raw_entries = workflow.get("entry_nodes")
        if isinstance(raw_entries, list) and raw_entries:
            declared_entries = [str(x) for x in raw_entries]
        elif isinstance(raw_entries, str) and raw_entries:
            declared_entries = [raw_entries]
    if declared_entries is None:
        flagged = [
            str(n["id"])
            for n in nodes_raw
            if isinstance(n, dict) and n.get("entry") is True and "id" in n
        ]
        if flagged:
            declared_entries = flagged

    # [P0-11] Canonical sources are computed over REAL predecessor routes:
    # self-loops and compensation (undo) edges do not make a node preceded,
    # so a compensation back-edge can never silently re-root the workflow.
    preceded: set[str] = set()
    for _e in edges:
        if _e.to_node == _e.from_node:
            continue
        if _e.type is EdgeType.COMPENSATION:
            continue
        preceded.add(_e.to_node)
    sources = [nid for nid in declared_order if nid not in preceded]
    # Undo destinations are failure-routing targets, never entry candidates:
    # a node reachable ONLY via compensation cannot start the workflow.
    comp_targets = {_e.to_node for _e in edges if _e.type is EdgeType.COMPENSATION}
    entry_candidates = [s for s in sources if s not in comp_targets] or sources

    if declared_entries is not None:
        unknown = [x for x in declared_entries if x not in nodes]
        if unknown:
            raise PlanValidationError(f"entry_nodes reference unknown nodes: {unknown}")
        entry_node_ids = declared_entries
    elif legacy_linearized:
        entry_node_ids = [declared_order[0]]
    elif len(entry_candidates) == 1:
        entry_node_ids = entry_candidates
    else:
        raise PlanValidationError(
            "Ambiguous workflow entry: multiple source nodes "
            f"{sorted(entry_candidates) or '<none>'} with no explicit declaration. "
            "Declare workflow.entry_nodes (or node entry: true)."
        )
    for nid in entry_node_ids:
        nodes[nid] = NodeIR(
            node_id=nid,
            definition=copy.deepcopy(nodes[nid].definition),
            is_entry=True,
        )

    plan = WorkflowPlan(
        nodes=nodes,
        edges=edges,
        entry_node_ids=entry_node_ids,
        failure_policy=_resolve_failure_policy(scenario),
        legacy_linearized=legacy_linearized,
    )
    _validate_plan(plan)
    plan.evaluation_plan = compile_evaluation_plan(scenario, plan)
    return plan


def _resolve_failure_policy(scenario: dict[str, Any]) -> FailurePolicy:
    raw = scenario.get("failure_policy")
    workflow = scenario.get("workflow")
    if not raw and isinstance(workflow, dict):
        raw = workflow.get("failure_policy")
    if not raw:
        return FailurePolicy.FAIL_FAST
    key = str(raw).strip().lower()
    try:
        return FailurePolicy(key)
    except ValueError as err:
        raise PlanValidationError(
            f"Unknown failure_policy '{raw}'. Valid: {[p.value for p in FailurePolicy]}"
        ) from err


def _validate_plan(plan: WorkflowPlan) -> None:
    errors: list[str] = []

    reachable = set(plan.entry_node_ids)
    frontier = list(reachable)
    adjacency: dict[str, set[str]] = {}
    for e in plan.edges:
        adjacency.setdefault(e.from_node, set()).add(e.to_node)
    while frontier:
        current = frontier.pop()
        for nxt in adjacency.get(current, ()):  # noqa: B007
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)

    unreachable = sorted(set(plan.nodes) - reachable)
    if unreachable:
        errors.append(f"Unreachable nodes from entry: {unreachable}")

    # A node is terminal-capable when it has no unconditional-success outgoing
    # edges: pure retry/compensation/error handlers may still complete the
    # workflow by exhausting their routing.
    _non_terminal_edge_types = {
        EdgeType.RETRY,
        EdgeType.COMPENSATION,
        EdgeType.ERROR,
        EdgeType.TIMEOUT,
    }
    terminal_nodes = [
        nid
        for nid in plan.nodes
        if not adjacency.get(nid)
        or all(e.type in _non_terminal_edge_types for e in plan.outgoing(nid))
    ]
    if not terminal_nodes:
        errors.append("Workflow has no terminal node (every node has outgoing edges)")

    for e in plan.edges:
        if e.type == EdgeType.CONDITION and e.predicate is None:
            errors.append(f"Edge '{e.edge_id}' of type '{e.type.value}' requires a predicate")

    _validate_plan_semantics(plan, errors, reachable)

    # [A2] Minimum-oracle rule: a node that declares no oracle assertion
    # source can never yield a truth-authoritative verdict, so it is rejected
    # at compile time rather than silently passing at runtime.
    oracle_free: list[str] = []
    for _nid in plan.nodes:
        node = plan.nodes[_nid]
        definition = node.definition
        criteria = definition.get("success_criteria")
        hygiene = definition.get("state_hygiene")
        hygiene_rules = hygiene.get("rules") if isinstance(hygiene, dict) else None
        expected_outcome = definition.get("expected_outcome")

        def _non_empty_list(v: Any) -> bool:
            return isinstance(v, list) and len(v) > 0

        if not (
            _non_empty_list(criteria)
            or _non_empty_list(hygiene_rules)
            or _non_empty_list(expected_outcome)
        ):
            oracle_free.append(_nid)
    if oracle_free:
        errors.append(
            "Minimum-oracle rule violated (NO_ASSERTIONS) — nodes declare no "
            "success_criteria, state_hygiene rules, or expected_outcome: "
            f"{sorted(oracle_free)}"
        )

    if errors:
        raise PlanValidationError("Invalid workflow plan: " + "; ".join(errors))


def _strongly_connected_components(plan: WorkflowPlan) -> list[list[str]]:
    """
    Iterative Tarjan SCC over the compiled graph (no recursion limits).
    Compensation edges are excluded: they are undo-routes, not iteration loops.
    """
    idx: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0

    successors = {
        nid: [e.to_node for e in plan.outgoing(nid) if e.type != EdgeType.COMPENSATION]
        for nid in plan.nodes
    }

    for root in plan.nodes:
        if root in idx:
            continue
        idx[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        call: list[tuple[str, Any]] = [(root, iter(successors[root]))]
        while call:
            v, iterator = call[-1]
            advanced = False
            for w in iterator:
                if w not in idx:
                    idx[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    call.append((w, iter(successors[w])))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], idx[w])
            if advanced:
                continue
            call.pop()
            if call:
                parent = call[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == idx[v]:
                component: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == v:
                        break
                components.append(component)
    return components


def _validate_plan_semantics(plan: WorkflowPlan, errors: list[str], reachable: set[str]) -> None:
    """
    [A6] Semantic validation over the normalized graph:
      1. Default-edge uniqueness per source (an unambiguous fallback).
      2. Conditional edges require distinct priorities (deterministic,
         order-independent selection).
      3. Explicit join cardinality cannot exceed the node's incoming degree.
      4. Compensation legality: no self-compensation and the compensated node
         must be reachable from entry (you can only undo what can run).
      5. Loop nodes (SCC members / self-edges) must declare an explicit
         max_visitations budget.
    """
    outgoing_by_source: dict[str, list[EdgeIR]] = {}
    for e in plan.edges:
        outgoing_by_source.setdefault(e.from_node, []).append(e)

    # 0. Outgoing successor exclusivity (P2.3).
    # Exactly one legal semantics per outgoing-edge class:
    # - single sequential successor, OR
    # - mutually-exclusive conditions (+ optional single default), OR
    # - explicit parallel fan-out (>= 2 parallel edges).
    for nid, outs in outgoing_by_source.items():
        seq_edges = [e for e in outs if e.type == EdgeType.SEQUENTIAL]
        par_edges = [e for e in outs if e.type == EdgeType.PARALLEL]
        cond_edges = [e for e in outs if e.type == EdgeType.CONDITION]
        def_edges = [e for e in outs if e.type == EdgeType.DEFAULT]

        if len(seq_edges) > 1:
            errors.append(
                f"Ambiguous successor set on node '{nid}' — multiple sequential edges declared "
                f"({[e.edge_id for e in seq_edges]}). Use 'parallel' for explicit fan-out."
            )
        if seq_edges and par_edges:
            errors.append(
                f"Ambiguous successor set on node '{nid}' — mixed sequential and parallel edges. "
                "Declare either a single sequential successor or explicit parallel fan-out."
            )
        if par_edges and cond_edges:
            errors.append(
                f"Ambiguous successor set on node '{nid}' — mixed parallel and conditional edges."
            )
        if seq_edges and cond_edges and not def_edges:
            errors.append(
                f"Ambiguous successor set on node '{nid}' — unconditional sequential edge "
                "alongside conditional edges without 'default' designation. Use 'default'."
            )

    # 1. Default uniqueness.
    ambiguous_defaults = sorted(
        nid
        for nid, outs in outgoing_by_source.items()
        if sum(1 for e in outs if e.type == EdgeType.DEFAULT) > 1
    )
    if ambiguous_defaults:
        errors.append(
            f"Ambiguous fallback routing — multiple 'default' edges from nodes {ambiguous_defaults}"
        )

    # 2. Condition exclusivity via distinct priorities.
    priority_clashes: list[str] = []
    for nid, outs in outgoing_by_source.items():
        seen_priorities: set[int] = set()
        for e in outs:
            if e.type != EdgeType.CONDITION:
                continue
            if e.priority in seen_priorities:
                priority_clashes.append(f"{nid} (priority={e.priority})")
            seen_priorities.add(e.priority)
    if priority_clashes:
        errors.append(
            "Non-exclusive conditional routing — duplicate priorities among "
            f"'condition' edges make selection order-dependent: {sorted(set(priority_clashes))}"
        )

    # 3. Join cardinality <= incoming degree (all declaration forms).
    join_violations: list[str] = []
    for nid, node in plan.nodes.items():
        indegree = len(plan.incoming(nid))
        if indegree == 0:
            continue
        try:
            _, n_req = node.join_spec({e.edge_id for e in plan.incoming(nid)})
        except PlanValidationError as exc:
            join_violations.append(f"{nid} ({exc})")
            continue
        if n_req > indegree:
            join_violations.append(f"{nid} (join n={n_req} > indegree={indegree})")
    if join_violations:
        errors.append(f"Join cardinality exceeds incoming degree: {join_violations}")

    # 4. Compensation legality. Failure routing can only originate from a
    # node that can actually execute, so the compensating SOURCE must be
    # forward-reachable (via non-compensation edges); self-compensation and
    # dead-source compensation routes are rejected. Targets are exempt from
    # reachability: compensate_then_fail semantics legitimately route to
    # nodes that have not executed yet.
    forward_reachable = set(plan.entry_node_ids)
    frontier_fwd = list(forward_reachable)
    forward_adjacency: dict[str, set[str]] = {}
    for e in plan.edges:
        if e.type != EdgeType.COMPENSATION:
            forward_adjacency.setdefault(e.from_node, set()).add(e.to_node)
    while frontier_fwd:
        current = frontier_fwd.pop()
        for nxt in forward_adjacency.get(current, ()):  # noqa: B007
            if nxt not in forward_reachable:
                forward_reachable.add(nxt)
                frontier_fwd.append(nxt)

    compensation_violations: list[str] = []
    for e in plan.edges:
        if e.type != EdgeType.COMPENSATION:
            continue
        if e.to_node == e.from_node:
            compensation_violations.append(f"'{e.edge_id}' self-compensation")
        elif e.from_node not in forward_reachable:
            compensation_violations.append(
                f"'{e.edge_id}' compensation originates from unreachable node '{e.from_node}'"
            )
    if compensation_violations:
        errors.append(f"Illegal compensation edges: {compensation_violations}")

    # 5. Explicit visitation budgets inside loop SCCs.
    loop_nodes: set[str] = set()
    for component in _strongly_connected_components(plan):
        if len(component) > 1:
            loop_nodes.update(component)
        elif component[0] in {e.to_node for e in plan.outgoing(component[0])}:
            loop_nodes.add(component[0])
    unbounded_loops = sorted(
        nid for nid in loop_nodes if plan.nodes[nid].definition.get("max_visitations") is None
    )
    if unbounded_loops:
        errors.append(
            "Loop nodes without explicit visitation budget — declare "
            f"max_visitations for {unbounded_loops}"
        )


PredicateResolver = Callable[[PredicateIR], tuple[bool, dict[str, Any]]]


def resolve_predicate_path(context: dict[str, Any], path: str | None) -> Any:
    """Resolves dotted predicate paths against the transition context."""
    from .utils.path_resolver import PathResolver

    if not path:
        return context
    if "." in path:
        root_name, remainder = path.split(".", 1)
        if root_name in context:
            return PathResolver.resolve(context[root_name], remainder)
    elif path in context:
        return context[path]
    return PathResolver.resolve(context.get("state", {}), path)


def evaluate_predicate(predicate: PredicateIR, context: dict[str, Any]) -> tuple[bool, Any]:
    """
    Evaluates a structured predicate against a transition context.
    Returns (result, observed_value) so evaluated predicates become evidence.
    """
    import re as _re

    if predicate.op == "compound":
        results = [evaluate_predicate(c, context) for c in predicate.clauses]
        observed = [{"passed": r, "observed": v} for r, v in results]
        passed = (
            all(r for r, _ in results) if predicate.logic == "all" else any(r for r, _ in results)
        )
        return passed, observed

    actual = resolve_predicate_path(context, predicate.path)
    op = predicate.op
    try:
        if op == "eq":
            return actual == predicate.value, actual
        if op == "ne":
            return actual != predicate.value, actual
        if op == "gt":
            return float(actual) > float(predicate.value), actual
        if op == "gte":
            return float(actual) >= float(predicate.value), actual
        if op == "lt":
            return float(actual) < float(predicate.value), actual
        if op == "lte":
            return float(actual) <= float(predicate.value), actual
        if op == "contains":
            if isinstance(actual, (list, tuple, set)):
                return predicate.value in actual, actual
            return str(predicate.value).lower() in str(actual).lower(), actual
        if op == "exists":
            return actual is not None, actual
        if op == "not_exists":
            return actual is None, actual
        if op == "in":
            allowed = predicate.value if isinstance(predicate.value, list) else [predicate.value]
            return actual in allowed, actual
        if op == "regex":
            return bool(_re.search(str(predicate.value), str(actual))), actual
        if op == "truthy":
            return bool(actual), actual
    except (TypeError, ValueError):
        return False, actual
    return False, actual


__all__ = [
    "EXECUTION_IR_VERSION",
    "CompiledEvaluationPlan",
    "CompiledOracle",
    "EdgeIR",
    "EdgeType",
    "ExecutionIdentity",
    "ExecutionMode",
    "FailurePolicy",
    "NodeIR",
    "NodeVerdict",
    "PlanValidationError",
    "PredicateIR",
    "WorkflowPlan",
    "WorkflowStatus",
    "compile_evaluation_plan",
    "compile_workflow",
    "evaluate_predicate",
    "normalize_edge_type",
    "resolve_predicate_path",
]
