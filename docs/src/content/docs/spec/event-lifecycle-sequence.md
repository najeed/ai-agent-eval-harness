---
title: "Event Lifecycle & Chronological Emission Specification"
description: "Authoritative specification of the AgentV trace event lifecycle, emission sequence, and forensic invariants across system personas."
---

# Event Lifecycle & Chronological Emission Specification

The AgentV evaluation runtime produces an immutable, high-fidelity chronological event stream (`run.jsonl`). Every state transition—from environment initialization to tactical DAG node execution and terminal cryptographic sealing—is recorded sequentially.

This specification details the end-to-end event sequence, the forensic invariants governing the stream, and persona-specific operational guides.

---

## 1. End-to-End Chronological Emission Sequence

An evaluation session transitions through five distinct phases:

```
[ Phase 1: Initialization ]
       │  run_start
       │  strategy_start (pass_at_k)
       │  phase_start (pass_at_k_execution)
       ▼
[ Phase 2: Per-Attempt Workflow & DAG Execution (k = 1..attempts) ]
       │  routing_resolved (optional)
       │  execution_graph_node (status="running")
       │  maneuver_start
       │  subtask_start
       │    ├── turn_start
       │    │     step_start (protocol handshake)
       │    │     tool_call / tool_result (sandbox-authoritative) OR
       │    │     external_tool_call / external_tool_result (external telemetry receipt)
       │    │     hitl_pause / approval_created / approval_resolved / hitl_resume (optional)
       │    └── turn_end
       │  maneuver_end
       │  execution_graph_node (status="completed" | "failed" | "skipped")
       │  execution_graph_edge (branch routing & predicate evidence)
       │  parallel_state_merged (if parallel fan-in)
       ▼
[ Phase 3: Aggregation & Mission Conclusion ]
       │  phase_end (pass_at_k_execution)
       │  error (only on unhandled failure)
       │  strategy_end (pass_at_k telemetry verdict)
       ▼
[ Phase 4: Authoritative Monotonic Terminal Boundary ]
       │  run_end (strictly final; carries mandatory finalization block)
       ▼
[ Phase 5: Post-Run Sealing & Attestation (Verification Pipeline) ]
          run_manifest.json (pre-cert) / execution_manifest.json
          trace_sealed / certification_failed
          <run_id>_vc.json + .sealed
```

---

## 2. Exhaustive Event Inventory & Sequence

| Step | Event Name | Emitting Component | Scope | Core Fields / Payload | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `run_start` | `eval_runner/runner.py` | Run | `run_id`, `scenario_id`, `k_attempts`, `execution_mode`, `execution_mode_declared`, `reproducibility_fingerprint`, `is_resume` | Session dispatch. Establishes execution truth level, seed contract, and resumption flag. |
| **2** | `strategy_start` | `eval_runner/runner.py` | Strategy | `run_id`, `strategy`, `k` | Demarcates mission exploration strategy (e.g., `pass_at_k`). |
| **3** | `phase_start` | `eval_runner/runner.py` | Phase | `run_id`, `phase` (`"pass_at_k_execution"`), `k` | Opens execution span for attempt iterations. |
| **4** | `routing_resolved` | `eval_runner/session.py` | Attempt | `capabilities`, `resolved_protocol`, `resolved_endpoint`, `source` | Dynamic adapter and endpoint discovery via capability registry. |
| **5** | `execution_graph_node` | `eval_runner/workflow_interpreter.py` | Node | `scenario_node_id`, `execution_instance_id`, `status="running"`, `attempt` | Deterministic pre-pass announcing node activation before task dispatch. |
| **6** | `maneuver_start` | `eval_runner/session.py` | Node | `node_id`, `task` | Demarcates multi-turn tactical node maneuver. |
| **7** | `subtask_start` | `eval_runner/session.py` | Subtask | `subtask_id`, `task_description` | Binds prompt and subtask boundaries. |
| **8** | `turn_start` | `eval_runner/session.py` | Turn | `turn`, `task_id` | Opens turn conversation cycle ($1 \dots \text{max\_turns}$). |
| **9** | `step_start` | `eval_runner/session.py` | Step | `step` (`protocol`) | Records protocol usage in forensic sequence ledger. |
| **10** | `tool_call` | `eval_runner/session.py` | Turn | `tool`, `arguments`, `call_id` | Dispatched when sandbox executes local/containerized tool invocation. |
| **11** | `tool_result` | `eval_runner/session.py` | Turn | `tool`, `result`, `call_id`, `error` | Dispatched when sandbox tool execution returns payload or error. |
| **12** | `external_tool_call` | `eval_runner/session.py` | Turn | `run_id`, `node_id`, `task_id`, `turn`, `order`, `tool`, `arguments`, `source="external_agent_telemetry"`, `provenance="reported"`, `receipt_hash` | Dispatched upon ingesting self-reported external agent tool calls. Binds deterministic SHA3-256 receipt hash. |
| **13** | `external_tool_result` | `eval_runner/session.py` | Turn | `run_id`, `node_id`, `task_id`, `turn`, `order`, `tool`, `result`, `result_summary`, `source="external_agent_telemetry"`, `provenance="reported"`, `receipt_hash` | Dispatched upon ingesting self-reported external agent tool return payloads or summaries. |
| **14** | `hitl_pause` | `eval_runner/session.py` | Turn | `task_id`, `prompt`, `approval_id` | Suspends execution when human intervention/approval is required. |
| **15** | `approval_created` | `eval_runner/session_components/approval_manager.py` | Turn | `approval_id`, `run_id`, `node_id`, `task_id`, `tool_name`, `arguments`, `status="pending"`, `created_at` | Emitted when formal HITL approval request is generated and stored in pending vault. |
| **16** | `approval_resolved` | `eval_runner/session_components/approval_manager.py` | Turn | `approval_id`, `run_id`, `decision` (`approved`\|`denied`), `resolved_by`, `resolved_at`, `reason` | Emitted when human reviewer grants or rejects pending approval request. |
| **17** | `hitl_resume` | `eval_runner/session.py` | Turn | `task_id`, `response`, `approved` | Resumes execution with operator feedback or rejection payload. |
| **18** | `turn_end` | `eval_runner/session.py` | Turn | `turn`, `task_id` | Concludes conversational turn after agent action processing. |
| **19** | `maneuver_end` | `eval_runner/session.py` | Node | `node_id` | Concludes tactical maneuver after state parity and oracle scoring. |
| **20** | `execution_graph_node` | `eval_runner/workflow_interpreter.py` | Node | `scenario_node_id`, `status="completed"|"failed"|"skipped"`, `duration_ms`, `failure_class` | Authoritative node completion verdict with duration and failure taxonomy. |
| **21** | `execution_graph_edge` | `eval_runner/workflow_interpreter.py` | Transition | `from_scenario_node_id`, `to_scenario_node_id`, `edge_type`, `evaluated_predicate`, `transition_reason` | Graph routing evidence showing why a branch, retry, or fallback was traversed. |
| **22** | `parallel_state_merged` | `eval_runner/session.py` | Wave | `run_id`, `merge_order`, `keys_affected` | Deterministic post-gather state reconciliation across concurrent forks. |
| **23** | `phase_end` | `eval_runner/runner.py` | Phase | `run_id`, `phase` (`"pass_at_k_execution"`) | Closes execution phase span across attempts. |
| **24** | `error` | `eval_runner/runner.py` | Run | `message`, `traceback`, `run_id` | Dispatched upon post-processing or unhandled harness exceptions. |
| **25** | `strategy_end` | `eval_runner/runner.py` | Strategy | `run_id`, `strategy`, `status` (`"success"|"failure"`) | Mission telemetry completion event. |
| **26** | `run_end` | `eval_runner/runner.py` | Run | `run_id`, `status`, `passed`, `score`, `pass_at_k`, `attempt_statistics`, `finalization` | **Strict monotonic terminal event.** Atomically seals run outcomes and cryptographic hashes. |
| **27** | `trace_sealed` | `eval_runner/verifier.py` | Run | `run_id`, `trace_hash`, `signer_id`, `timestamp` | Emitted upon successful cryptographic trace signing and writing of `.sealed` sentinel marker. |
| **28** | `certification_failed` | `eval_runner/verifier.py` | Run | `run_id`, `reason`, `code` | Emitted when trace verification fails invariant validation or integrity checks. |

---

## 3. Persona-Specific Reference Guides

### A. For Security Auditors
**Objective**: Guarantee tamper-evident audit trails, monotonic terminal boundaries, and verifiable non-repudiation.

1. **The Monotonic Terminal Boundary Invariant**:
   - `run_end` MUST be the final event in `run.jsonl`.
   - The embedded `finalization` payload contains:
     - `scenario_hash`: SHA3-256 over canonicalized scenario definition.
     - `evidence_root_hash`: Merkle root over all assertion and node records.
     - `finalization_hash`: Cryptographic digest of the finalization record itself.
   - **Audit Guard**: If any event appears after `run_end`, the `CertificationService` flags a *Monotonic Terminal Boundary Violation* and fails closed with outcome `"inconclusive"`. No certificate is issued.

2. **Monotonic Resumption Continuation Invariant (`is_resume=True`)**:
   - When a run pauses for human operator approval (`PAUSED_FOR_APPROVAL`) and later resumes via `agentv resume` or the visual console:
     - `runner.py` validates that the run lifecycle is not in terminal states (`FINALIZING`, `SEALED`, `INVALID`).
     - The existing evidence vault (`runs/<run_id>/`) and event ledger (`run.jsonl`) are preserved rather than overwritten or re-created.
     - `flight_recorder.py` inspects the existing `run.jsonl` to discover the highest existing sequence number (`initial_seq = max(_seq)`) and initializes `_sequence_numbers[run_id] = initial_seq`.
     - Resumed events append monotonically with strictly increasing sequence numbers (`_seq = initial_seq + 1, initial_seq + 2, ...`), preventing sequence collisions, duplicate IDs, or chronological gaps.
     - **Contract Snapshot Lock**: On resumption, `runner.py` reloads and locks the original `execution_manifest.json` and `scenario_resolved.json` from the vault. Scenario and configuration snapshots cannot be altered post-launch.

3. **Cryptographic Trace Sealing**:
   - Post-run execution of `agentv certify` computes a SHA3-256 digest over the raw `run.jsonl`.
   - The resulting hash is signed using Ed25519 (`system_id` or enterprise KMS/HSM).
   - Writes the `.sealed` sentinel marker and emits `trace_sealed`. Any modification to `run.jsonl` breaks hash verification during `agentv verify` or release gate checks (`agentv gate`).

4. **Execution Truth Levels**:
   - Traces lacking explicit `execution_mode: "live"` or `"hybrid"` are stamped `provisional: true`.
   - Provisional runs can NEVER be certified as authoritative for enterprise compliance or safety attestations.

---

### B. For Agent Integrators
**Objective**: Build compliant agent adapters, manage multi-turn communication, and integrate tool calling and HITL workflows.

1. **Protocol Handshake & Routing**:
   - Adapters declare communication protocols (`http`, `local`, `socket`, `stdio`).
   - The harness emits `routing_resolved` with target endpoints before task execution.
   - At each turn, `step_start` logs the active protocol in the sequence ledger.

2. **Sandbox-Authoritative Tool Execution vs. External Telemetry Ingestion**:
   - **Sandbox Tool Calling**: When the agent requests tool invocation executed by the local/containerized AgentV sandbox, the harness emits `tool_call` and executes the tool in the sandbox, emitting `tool_result`.
   - **External Agent Telemetry**: When integrating remote or autonomous agents that execute tools within their own private environment (e.g., self-hosted agent frameworks), the agent returns an execution trajectory or receipt.
     - The harness ingests these steps via `session.py:ingest_external_agent_telemetry`.
     - Emits `external_tool_call` and `external_tool_result` with explicit provenance attributes:
       - `source: "external_agent_telemetry"`
       - `provenance: "reported"`
       - `receipt_hash: "sha3_256:<hex>"` (canonical RFC 8785 JSON digest of order, tool, arguments, result, and endpoint).
     - **Integrity Rule**: External telemetry receipts are strictly tracked and counted in `CertificationService` under `external_tool_calls_observed`, and are **never** relabeled as AgentV-sandbox-authoritative.

3. **Human-In-The-Loop (HITL) & Approval Flow**:
   - When an agent requests a sensitive or restricted action requiring manual review, the turn enters human-in-the-loop suspension:
     1. The harness emits `hitl_pause` containing `approval_id`, `task_id`, and prompt.
     2. `SessionApprovalManager` persists the request and emits `approval_created` with tool arguments and timestamp.
     3. The run status transitions to `PAUSED_FOR_APPROVAL`, halting engine loops without finalizing the run.
     4. A human operator evaluates the pending request via the Visual Console or CLI (`agentv approve` / `agentv reject`).
     5. `SessionApprovalManager` emits `approval_resolved` with `decision` (`approved` or `denied`) and operator identity.
     6. If approved, `runner.py` resumes execution (`is_resume=True`), emitting `hitl_resume` with operator feedback. If rejected, execution aborts and the node fails closed with `POLICY_DENIED`.

---

### C. For Industry Evaluators
**Objective**: Measure domain-specific capability, analyze pass@k reliability, and verify state transitions.

1. **Strategy Telemetry & Pass@K**:
   - `strategy_start` and `strategy_end` demarcate the mission-level evaluation.
   - Pass@K uses unbiased estimators over executed attempts. All attempts are independently seeded ($S_k = S_{\text{base}} + k - 1$).
   - `attempt_statistics` on `run_end` provides:
     - `attempt_success_rate`: Proportion of successful attempts.
     - `all_pass`: Strict conjunctive success ($k$ of $k$).
     - `any_pass`: Disjunctive success ($\ge 1$ of $k$).

2. **Transition-Based State Parity**:
   - Between `maneuver_start` and `maneuver_end`, the sandbox tracks world state changes.
   - State before and after each node is hashed with SHA3-256 (`state_before_hash`, `state_after_hash`).
   - Node verdicts combine conversational metrics (`metrics_calculator`), state hygiene rules, and transition parity verifications.

---

### D. For Platform Extenders & Core Builders
**Objective**: Extend the event bus, introduce custom DAG nodes, and implement structured concurrency.

1. **Decoupled Event Bus (`eval_runner/events.py`)**:
   - Telemetry uses a publisher-subscriber model (`EventEmitter`).
   - Payloads are automatically sanitized against PII, API tokens, JWTs, and bearer headers before broadcast.
   - Subscriptions run asynchronously or synchronously without mutating engine control flow.

2. **Canonical Execution IR & Graph Scheduling**:
   - Workflows compile to a `WorkflowPlan` executed by `WorkflowInterpreter`.
   - Nodes transition deterministically: `pending` $\rightarrow$ `running` $\rightarrow$ `completed` / `failed` / `skipped`.
   - Node activations emit `execution_graph_node`.
   - Branch selections evaluate typed predicates and emit `execution_graph_edge` with observed values, ensuring complete graph auditability.

3. **Structured Concurrency**:
   - Sibling DAG branches run concurrently via `asyncio.gather`.
   - Sandboxes are isolated forks (`sandbox.fork(exec_id)`).
   - Upon convergence, `_on_batch_complete` performs a deterministic merge in canonical order and emits `parallel_state_merged`.
