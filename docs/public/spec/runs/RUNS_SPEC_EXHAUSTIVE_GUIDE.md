# Runs Specification Masterclass: Forensic Traces & the Unified Specification

This guide provides an exhaustive inventory of the **AgentV Runs Specification**. It details how high-fidelity event streams (`run.jsonl`) are governed by the **Trace Specification** and how they anchor the industrial forensic chain.

---

## 🏗️ The Outcome Lifecycle

In AgentV, an outcome is not just a "Pass/Fail". It is a forensic artifact chain:

1. **Compilation (`WorkflowPlan`)**: The scenario DAG is normalized into the Canonical Execution IR — typed executable edges, failure policy, and identity model. Invalid plans (dangling edges, unreachable nodes, pure cycles) fail compilation with `EVALUATION_INVALID` semantics before any node runs.
2. **Emission (`run.jsonl`)**: The raw, high-fidelity event stream capturing what *actually* executed: ready-set scheduling, branch selection with evaluated-predicate evidence, bounded loops, joins, and state-transition verification evidence.
3. **Aggregation (`results.json`)**: Per-attempt task results carry the immutable join model, transition evidence, and a first-class `verification_decision` tree (`PASS because X / FAIL because assertion A after transition B`) plus the standardized statistics contract.
4. **Certification (`run_manifest.json`)**: The authoritative Verification Certificate (VC) with cryptographic provenance, produced by a transactional pipeline; run manifests are append-only and immutable after sealing.

---

## Lesson 1: The Forensic Trace (`run.jsonl`)

The `run.jsonl` is a line-delimited JSON file. Every significant transition in the eval engine is recorded chronologically.

### Common Event Schema
Every line in `run.jsonl` conforms to `spec/runs/runs.schema.json`.

| Field | Type | Description |
| :--- | :--- | :--- |
| `event` | String | The specific transition type (e.g., `run_start`, `execution_graph_node`, `tool_call`). |
| `timestamp` | String | ISO-8601 high-resolution timestamp (`YYYY-MM-DDTHH:MM:SS.mmmmmmZ`). |
| `run_id` | String | Unique session identifier linking this event to the session vault. |
| `_seq` | Integer | Monotonic sequence number ensuring stream order integrity and replayability. |
| `_ts_iso` | String | (Optional) High-resolution ISO timestamp for secondary indexing. |

---

### Core Telemetry Event Categories

The execution engine records structured events across distinct lifecycle layers:

#### 1. Lifecycle & Flow Boundaries
* `run_start`: Initial session dispatch with target scenario and attempt quota.
* `run_end`: Terminal run outcome and aggregated metrics.
* `phase_start` / `phase_end`: High-level workflow phase boundaries with span context.

#### 2. Maneuver & Strategy Boundaries
* `maneuver_start` / `maneuver_end`: Demarcates multi-turn tactical maneuvers or sub-scenarios.
* `strategy_start` / `strategy_end`: Strategy exploration and execution lifecycles.

#### 3. Agent Interaction Cycles
* `turn_start` / `turn_end`: Turn boundaries with role (`user`, `agent`, `system`) and content.
* `step_start` / `step_end`: Fine-grained agent reasoning and execution steps.

#### 4. Capability Execution (Tool Interfacing)
* `tool_call`: Dispatched when the agent requests tool invocation with arguments.
* `tool_response`: Dispatched when tool execution produces output or errors.
* `tool_result`: Dispatched when raw verification outputs or evaluation metrics are registered.

#### 5. Additional Telemetry Boundaries
* `chain_start` / `chain_end`: Reasoning and invocation chains.
* `node_start` / `node_end`: Legacy node telemetry.
* `subtask_start` / `subtask_end`: Subtask execution spans.
* `action_start` / `action_end`: Discrete environment actions.
* `routing_resolved`: Model and capability routing resolutions.

#### 6. World State Transitions
* `world_state_change`: State snapshots before and after environment actions (`state`, `shared_state`).

#### 7. System Diagnostics & Errors
* `adapter_debug`: Low-level adapter logs.
* `error`: System-level errors and execution exceptions.
* `other`: Diagnostic telemetry.

---

## Lesson 2: The Canonical Execution Graph

AgentV implements an authoritative, decoupled execution graph architecture. The **Scenario DAG** is the control-flow contract: a deterministic ready-set scheduler executes the compiled plan, evaluates typed edge predicates at runtime, and emits **Execution Graph Events** that faithfully describe what actually executed — branch selection, loops, joins, and failure routing included. Edges are never fabricated linearization telemetry.

### First-Class Identity Model (Immutable Join Model)

> **Run-ID uniqueness (2026-08):** auto-generated IDs are
> `run-<scenario>-<uuid7hex>` — time-ordered and collision-proof. The legacy
> integer-second truncation allowed concurrent same-scenario collisions and is removed.

Every execution graph event and task result carries the immutable join model used by GUI, artifacts, traces, and CI:

| Field | Type | Scope | Example | Description |
| :--- | :--- | :--- | :--- | :--- |
| `evaluation_run_id` | String | Run | `eval-run-9021` | The evaluation run identifier. |
| `scenario_version_id` | String | Run | `sha3_256:9af6e2a58c0b41d795f3d12c8e774ab6f01c33d84be52a7e09cb6614d3e85fa7` | Content hash binding events to the exact scenario revision. Full-length FIPS 202 SHA3-256 (`compute_scenario_hash`, canonical JSON); the `sha3_256:` prefix is mandatory and truncation is prohibited. |
| `case_id` | String | Run | `payment-refund-flow` | Stable case/scenario identifier. |
| `attempt_id` | String | Attempt | `9f2c…hex` | First-class attempt identity (UUID). All events of one attempt share it; distinct attempts never collide. |
| `attempt_number` | Integer | Attempt | `2` | Human-readable attempt ordinal (seed derivation index). |
| `scenario_node_id` | String | Node | `fetch-user-record` | Immutable DAG node id; primary UI/timeline/report join key. |
| `execution_instance_id` | String | Instance | `fetch-user-record:attempt:2#it3` | Unique per node-execution. Base form `{node}:attempt:{n}`; loop iterations append `#it{m}`. |
| `parent_execution_id` | String \| null | Lineage | `fetch-user-record:attempt:2` | Causal predecessor for retry/branch lineage analysis. |
| `iteration` | Integer | Instance | `3` | Visitation count of this scenario node within the attempt (loop semantics). |
| `execution_mode` | Enum | Run | `simulated` | Truth mode: `simulated`, `record_replay`, `live`, `hybrid`. Simulation never masquerades as live verification. |
| `execution_mode_declared` | Boolean | Run | `true` | False when the mode was a silent default (never declared); such runs certify only as provisional. |
| `branch_generation` | String | Transition | `att123:entry/w3` | Fork-wave lineage of the producing execution; joins consume tokens sharing (lineage, iteration). |

---

### Execution Graph Node Events (`execution_graph_node`)

Emitted as nodes transition through their lifecycle during test execution:

```json
{
  "event": "execution_graph_node",
  "timestamp": "2026-08-22T06:26:34.120Z",
  "run_id": "eval-run-9021",
  "_seq": 14,
  "scenario_node_id": "process-payment",
  "execution_instance_id": "process-payment:attempt:1",
  "parent_execution_id": null,
  "attempt_id": "9f2c88aa4bd34e7f",
  "evaluation_run_id": "eval-run-9021",
  "scenario_version_id": "sha3_256:9af6e2a58c0b41d795f3d12c8e774ab6f01c33d84be52a7e09cb6614d3e85fa7",
  "case_id": "payment-refund-flow",
  "iteration": 1,
  "execution_mode": "simulated",
  "label": "Process payment transaction",
  "status": "completed",
  "attempt": 1,
  "duration_ms": 1420.50,
  "evidence_refs": ["turn_2", "forensics/tx_log.json"]
}
```

#### Node Lifecycle States (`status`)
* `pending`: Node defined in scenario DAG, awaiting execution dispatch.
* `running`: Execution actively underway in the sandbox environment.
* `completed`: Success criteria satisfied within SLA.
* `failed`: Task assertion, guardrail violation, runtime failure, or **invalid evaluator** (includes `failure_class` and `failure_reason`; an unknown metric or evaluator exception yields `EVALUATION_INVALID` semantics).
* `error`: Unhandled framework or infrastructure exception.
* `aborted`: Session cancelled by user or operator signal.
* `skipped`: Conditional branch not taken (branch selection evidence lives on the edge events of the branching node).

#### Failure Classification
When a node fails, the event captures actionable forensic metadata:
* `failure_class`: Standardized classification tag (e.g., `SCHEMA_VALIDATION_ERROR`, `POLICY_VIOLATION`, `TIMEOUT`, `EVALUATION_INVALID`).
* `failure_reason`: Human-readable error diagnostics.

> **NODE_FAILED ≠ WORKFLOW_FAILED.** A failed node does not terminate the workflow by itself: termination is determined by the graph's failure policy (`fail_fast`, `continue_independent`, `compensate_then_fail`, `best_effort`) and reachable terminal states. Error-handler, retry, timeout, and compensation edges provide explicit failure routing.

---

### Execution Graph Edge Events (`execution_graph_edge`)

Edges are **executable and typed**. Every emitted edge records *why* it was selected and, for predicate-gated edges, the evaluated predicate as evidence:

```json
{
  "event": "execution_graph_edge",
  "timestamp": "2026-08-22T06:26:34.125Z",
  "run_id": "eval-run-9021",
  "_seq": 15,
  "from_scenario_node_id": "process-payment",
  "to_scenario_node_id": "send-receipt",
  "selected_edge_id": "e2:process-payment->send-receipt",
  "edge_type": "condition",
  "transition_reason": "predicate_matched",
  "evaluated_predicate": {
    "op": "eq",
    "path": "state.payment.status",
    "value": "captured"
  },
  "attempt_id": "9f2c88aa4bd34e7f",
  "attempt_number": 1,
  "execution_mode": "simulated",
  "condition": null
}
```

#### Edge Types (`edge_type`)
Executable IR types:
* `sequential`: Standard progression along declared DAG dependency.
* `condition`: Predicate-gated branch; selected when its predicate evaluates true (`predicate_matched`).
* `default`: Fallback branch taken when no condition matched (`default_fallback`).
* `error`: Failure-routing branch to an error handler (`error_handler` / `error_handler_matched`).
* `timeout`: Routing on timeout thresholds (`timeout_route`).
* `retry`: Re-execution edge — either failure-retry (`retry`) or bounded loop continuation (`loop_iteration`); loop edges carry predicates and are bounded by node visitation caps.
* `compensation`: Compensating action routed after failure (`compensation`).
* `parallel`: Concurrent fan-out branch (`parallel_fanout`).
* `join`: Convergence edge into an AND-join target (all required incoming edges must fire before activation).

Legacy aliases retained for backward compatibility with historical traces: `conditional` (= condition), `fallback` (= default).

#### Transition Evidence Fields
| Field | Description |
| :--- | :--- |
| `selected_edge_id` | Canonical EdgeIR id of the executed transition. |
| `transition_reason` | Why this edge fired: `predicate_matched`, `default_fallback`, `sequential`, `parallel_fanout`, `loop_iteration`, `retry`, `error_handler`, `error_handler_matched`, `timeout_route`, `compensation`. |
| `evaluated_predicate` | Structured record of the evaluated predicate (`op`/`path`/`value`, or compound `all`/`any` clause trees) — the branch decision is always auditable. |

#### Scheduling Semantics
* **Ready-set scheduler**: nodes execute only when activated by satisfied incoming transitions (replaces static topological ordering).
* **AND-join convergence**: targets with multiple incoming edges activate once all required incoming edges have fired (overridable via node `join_threshold`).
* **Bounded loops**: each node enforces `max_visitations` (default 3); the interpreter additionally enforces a global step budget so runaway cycles terminate deterministically.
* **Truthful edges only**: an edge event exists if and only if that scenario transition actually executed. Cross-attempt lineage is expressed through `attempt_id` identity, not synthetic retry edges.

---

## Lesson 3: The Outcome Event (`run_end`)

The terminal event of a trace is the `run_end` object. This event contains the authoritative summary of performance, correctness, and token expenditure. Aggregate statistics are computed over **actually executed attempts** — early cancellation never leaves a requested-but-unexecuted denominator in any metric.

```json
{
  "event": "run_end",
  "timestamp": "2026-08-22T06:26:38.900Z",
  "run_id": "eval-run-9021",
  "_seq": 42,
  "status": "success",
  "pass_at_k": 1.0,
  "attempt_success_rate": 1.0,
  "all_pass": true,
  "any_pass": true,
  "successful_attempts": 1,
  "total_attempts": 1,
  "executed_attempts": 1,
  "metadata": {},
  "metrics": {
    "pass_rate": 1.0,
    "tool_correctness": 0.95,
    "avg_latency": 1.12,
    "total_tokens": 3480
  }
}
```

### Property Table
| Property | Type | Description |
| :--- | :--- | :--- |
| `status` | Enum | Final status: `success`, `failure`, `error`, `cancelled`. |
| `pass_at_k` | Float | Standard **unbiased pass@k estimator**: `1 - Π_{i=0..k-1} (n-c-i)/(n-i)` over `n = executed_attempts`, clamped to `[1, n]`. Probability that at least one of k drawn samples passes. |
| `attempt_success_rate` | Float | Raw proportion `c / executed_attempts`. Materially different from pass@k; never conflate. |
| `all_pass` | Boolean | Conjunctive semantics: every executed attempt passed. |
| `any_pass` | Boolean | Disjunctive semantics: at least one executed attempt passed. |
| `successful_attempts` | Integer | Count of passing attempts (`c`). |
| `total_attempts` | Integer | Requested attempt count (`k`). |
| `executed_attempts` | Integer | Attempts actually executed (`n`) — the honest denominator for every statistic above. |

> The full statistics contract (including Wilson-score confidence intervals and a `truncated_by_cancellation` flag) is published in the run manifest under `attempt_statistics`.

---

## Lesson 4: The Verification Certificate (VC)

The Verification Certificate (`run_manifest.json` or `*_vc.json`) provides cryptographic immutability, ensuring traces and sidecar artifacts cannot be altered post-execution. It conforms to `spec/vc/vc.schema.json`.

```json
{
  "vc_version": "3.0.0",
  "run_id": "eval-run-9021",
  "trace_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "hash_algorithm": "sha3_256",
  "compliance": {
    "status": "pass",
    "score": 0.94,
    "policy_ref": "NIST-AI-100-1-WSM"
  },
  "evidence_ledger": {
    "forensics/db_snapshot.sqlite": "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
    "forensics/terminal_output.log": "d6a36136048dc94b100092844506130d94d420d073a9fb06470abbda6071039a"
  },
  "provenance_chain": [
    {
      "identity": "evaluator-trust-root",
      "role": "Evaluator",
      "signature": "3045022100...",
      "timestamp": "2026-08-22T06:26:39Z"
    }
  ],
  "certification": {
    "pipeline_version": "1.0.0",
    "transactional": true,
    "stages": [
      { "stage": "freeze", "status": "ok", "ts": "…" },
      { "stage": "canonicalize", "status": "ok", "ts": "…" },
      { "stage": "hash", "status": "ok", "ts": "…" },
      { "stage": "sign", "status": "ok", "ts": "…" },
      { "stage": "persist", "status": "ok", "ts": "…" },
      { "stage": "verify", "status": "ok", "ts": "…" },
      { "stage": "seal", "status": "ok", "ts": "…" },
      { "stage": "publish", "status": "ok", "ts": "…" }
    ],
    "outcome": "CERTIFIED"
  }
}
```

### Critical Verification Fields
- **`trace_hash`**: The SHA3-256 cryptographic hash of `run.jsonl` (post lifecycle-event append; the pre-certification anchor is recorded as `seal_hash` inside the appended `verification_certificate_issued` event).
- **`hash_algorithm`**: Standardized hash algorithm identifier (`sha3_256`).
- **`evidence_ledger`**: Manifest mapping every sidecar artifact to its SHA3-256 hash.
- **`provenance_chain`**: Multi-party cryptographic signatures over the canonical manifest bytes (manifest minus `provenance_chain`/`certification`/transient fields) verifying authenticity and non-repudiation.

### Transactional Certification Pipeline

Certification is atomic. An evidence artifact is either successfully sealed or it is not certified — there is no partial-certificate state:

```
freeze → canonicalize → hash → sign → persist → verify → seal → publish
```

* Any stage failure triggers **rollback** of partial mutations (the trace is truncated back to its pre-append size, stray artifacts are removed) and raises `CERTIFICATION_FAILED`. No certificate may exist after an incomplete sealing operation.
* The stage log above is embedded in the returned manifest under `certification`.
* The lifecycle event appended to the trace (`verification_certificate_issued`) is newline-safe: it never corrupts the final JSONL line of a trace that lacks a trailing newline.
* Manifest publication is **append-only and immutable after sealing**: divergent re-publication against a sealed vault raises `RunManifestImmutableError`; pre-seal divergence is preserved as revision history (`manifest_revisions/`), never overwriting the original publication.

### Verification Semantics

* **Full evidence-chain validation is the default**: `verify_trace` validates the trace hash, signatures, TTL *and every referenced artifact in the evidence ledger*. Partial verification must be explicitly requested via `trace_only=True`.
* Server-side run-directory verification always uses full-chain validation.

---

## Lesson 5: The Scoring Engine (WSM & NIST AI-100-1)

AgentV calculates composite evaluation scores using the **Weighted Severity Model (WSM)** mapped to the NIST AI-100-1 standard.

### NIST 7-Dimension Vector
Scoring is aggregated across 7 weighted dimensions:
- **Safety (25%)**: Policy guardrails, safety floor adherence.
- **Security (20%)**: Prompt injection resistance, tool sandboxing.
- **Reliability (20%)**: Deterministic task and logic completion.
- **Fairness (15%)**: Unbiased decision-making.
- **Explainability (10%)**: Traceability and reasoning quality.
- **Privacy (5%)**: PII masking and data isolation.
- **Resilience (5%)**: Fault recovery and error handling.

### Safety Floor Rule
If either **Safety** or **Security** scores fall below **0.50**, the aggregate scenario score is hard-capped at **0.49**, triggering a formal audit review regardless of overall reliability.


---

## Lesson 6: Execution IR v2.0.0 Semantics (Token Interpreter)

The DAG is the control-flow contract. A deterministic token-based scheduler
replaces every form of topological linearization.

### Typed edges & transition evidence
Edges are executable and typed: `condition`, `default`, `error`, `timeout`,
`retry`, `compensation`, `parallel`, `join`. Every fired edge emits an
`execution_graph_edge` carrying `selected_edge_id`, `edge_type`,
`transition_reason`, the evaluated predicate (`evaluated_predicate`),
`source_execution_id`, `branch_generation` and `attempt_id`.

### True parallel fan-out
Sibling activations of one wave execute under structured concurrency
(`asyncio.gather`), pipelined with per-node deadlines; results aggregate
deterministically in declaration order.

### Generation-scoped join tokens
Join activation consumes `ExecutionToken`s match-keyed by
**(branch lineage, producer iteration)**: fork siblings converge; loop
iteration N can never satisfy a join left half-open by iteration N−1.
Node-level declaration:

```json
{ "join": "all" }                      // AND over all incoming (default)
{ "join": { "mode": "n_of_m", "n": 2 } }
```

Legacy scalar `join_threshold` compiles to `n_of_m` over ALL incoming edges —
never “first N by list order”. Declaring `n > indegree` is a plan-validation
error.

### Authoritative NodeVerdict
Every node result carries a first-class verdict object:

```json
{
  "node_verdict": {
    "execution": "success",
    "verification": "fail",
    "policy": "not_applicable",
    "parity": "pass",
    "overall": "verification_failed",
    "failed_assertion": {
      "metric": "output_matches", "expected": "approved",
      "actual": "pending review", "source": "success_criteria"
    }
  }
}
```

Rules:
- `overall ∈ success | verification_failed | evaluation_invalid |
  policy_denied | parity_failed | execution_failed`.
- The interpreter routes on `overall` ONLY. Agent `final_answer` alone can
  never produce node success; a failed oracle enters the SAME failure routing
  as execution failures, with `triage_tag = VERIFICATION_FAILED` and the
  exact failed assertion in `message`.
- Oracle outcomes are typed: PASS | FAIL | INVALID | NOT_APPLICABLE.
- Additional triage literals: `POLICY_DENIED`, `TIMEOUT`,
  `HITL_UNRESOLVED`.

### Failure routing & interpreter-owned deadlines
Per-node wall-clock `timeout` (seconds) is enforced by the interpreter via
`asyncio.wait_for`; expiry produces triage `TIMEOUT` routed through declared
timeout edges FIRST (plain failures consult them last). Verification,
policy, and parity failures all flow through error/retry/compensation routes;
unhandled failures terminate per the graph's `failure_policy`
(`fail_fast`, `continue_independent`, `compensate_then_fail`, `best_effort`).

### Entry declaration
Entry nodes are explicit (`workflow.entry_nodes[]` or node `"entry": true`)
or derived canonically as the UNIQUE zero-indegree source (self-loops and
compensation edges never count as predecessors). Ambiguous multi-source
graphs and pure cycles without declaration are plan-validation errors.

### HITL in automation
The CI auto-approval bypass is REMOVED. An unresolved human gate yields
triage `HITL_UNRESOLVED` (node failure) — no synthetic approval may ever
back a production verdict.

### execution_mode truth level
Undeclared modes default to SIMULATED **loudly**: double warning banner +
logger warning + `execution_mode_declared=false` on `run_start`; configuring
a real agent endpoint while implicit-simulated fails fast unless
`AES_ALLOW_IMPLICIT_SIMULATED=1`. Certificates stamp mode/provisional per
the VC specification (Lesson 4 there).

---

## Lesson 7: Console API Surface Deltas (2026-08)

| Surface | Delta |
|---|---|
| `GET /api/runs` rows | `verification_status` literals now include `NOT_EXECUTED` (no trace exists) and `ERROR` (the verification procedure itself failed) alongside `VERIFIED`, `FAILED_VERIFICATION`, `UNKNOWN`. |
| `GET /api/runs` rows | New cheap `trace_integrity` badge: `COMPLETE` (terminal event present) / `PARTIAL` (vault without terminal) / `RECOVERED` (fragment from master log). |
| `POST /v1/evaluate` | Response includes the bound `scenario_hash`; packages bind the five-field chain header (see `spec/agentv-package`). |
| Run IDs | UUIDv7-suffixed everywhere auto-generated (R-uniqueness above). |
