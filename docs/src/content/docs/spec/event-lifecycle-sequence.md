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
       │    │     tool_call / tool_result (optional)
       │    │     hitl_pause / hitl_resume (optional)
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
          run_manifest.json + <run_id>_vc.json + .sealed
```

---

## 2. Exhaustive Event Inventory & Sequence

| Step | Event Name | Emitting Component | Scope | Core Fields / Payload | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `run_start` | `eval_runner/runner.py` | Run | `run_id`, `scenario_id`, `k_attempts`, `execution_mode`, `execution_mode_declared`, `reproducibility_fingerprint` | Session dispatch. Establishes execution truth level and seed contract. |
| **2** | `strategy_start` | `eval_runner/runner.py` | Strategy | `run_id`, `strategy`, `k` | Demarcates mission exploration strategy (e.g., `pass_at_k`). |
| **3** | `phase_start` | `eval_runner/runner.py` | Phase | `run_id`, `phase` (`"pass_at_k_execution"`), `k` | Opens execution span for attempt iterations. |
| **4** | `routing_resolved` | `eval_runner/session.py` | Attempt | `capabilities`, `resolved_protocol`, `resolved_endpoint`, `source` | Dynamic adapter and endpoint discovery via capability registry. |
| **5** | `execution_graph_node` | `eval_runner/workflow_interpreter.py` | Node | `scenario_node_id`, `execution_instance_id`, `status="running"`, `attempt` | Deterministic pre-pass announcing node activation before task dispatch. |
| **6** | `maneuver_start` | `eval_runner/session.py` | Node | `node_id`, `task` | Demarcates multi-turn tactical node maneuver. |
| **7** | `subtask_start` | `eval_runner/session.py` | Subtask | `subtask_id`, `task_description` | Binds prompt and subtask boundaries. |
| **8** | `turn_start` | `eval_runner/session.py` | Turn | `turn`, `task_id` | Opens turn conversation cycle ($1 \dots \text{max\_turns}$). |
| **9** | `step_start` | `eval_runner/session.py` | Step | `step` (`protocol`) | Records protocol usage in forensic sequence ledger. |
| **10** | `tool_call` | `eval_runner/session.py` | Turn | `tool`, `arguments`, `call_id` | Dispatched when agent requests sandbox/external tool invocation. |
| **11** | `tool_result` | `eval_runner/session.py` | Turn | `tool`, `result`, `call_id`, `error` | Dispatched when tool execution produces return payload or error. |
| **12** | `hitl_pause` | `eval_runner/session.py` | Turn | `task_id`, `prompt`, `approval_id` | Suspends execution when human intervention/approval is required. |
| **13** | `hitl_resume` | `eval_runner/session.py` | Turn | `task_id`, `response`, `approved` | Resumes execution with operator feedback or rejection. |
| **14** | `turn_end` | `eval_runner/session.py` | Turn | `turn`, `task_id` | Concludes conversational turn after agent action processing. |
| **15** | `maneuver_end` | `eval_runner/session.py` | Node | `node_id` | Concludes tactical maneuver after state parity and oracle scoring. |
| **16** | `execution_graph_node` | `eval_runner/workflow_interpreter.py` | Node | `scenario_node_id`, `status="completed"|"failed"|"skipped"`, `duration_ms`, `failure_class` | Authoritative node completion verdict with duration and failure taxonomy. |
| **17** | `execution_graph_edge` | `eval_runner/workflow_interpreter.py` | Transition | `from_scenario_node_id`, `to_scenario_node_id`, `edge_type`, `evaluated_predicate`, `transition_reason` | Graph routing evidence showing why a branch, retry, or fallback was traversed. |
| **18** | `parallel_state_merged` | `eval_runner/session.py` | Wave | `run_id`, `merge_order`, `keys_affected` | Deterministic post-gather state reconciliation across concurrent forks. |
| **19** | `phase_end` | `eval_runner/runner.py` | Phase | `run_id`, `phase` (`"pass_at_k_execution"`) | Closes execution phase span across attempts. |
| **20** | `error` | `eval_runner/runner.py` | Run | `message`, `traceback`, `run_id` | Dispatched upon post-processing or unhandled harness exceptions. |
| **21** | `strategy_end` | `eval_runner/runner.py` | Strategy | `run_id`, `strategy`, `status` (`"success"|"failure"`) | Mission telemetry completion event. |
| **22** | `run_end` | `eval_runner/runner.py` | Run | `run_id`, `status`, `passed`, `score`, `pass_at_k`, `attempt_statistics`, `finalization` | **Strict monotonic terminal event.** Atomically seals run outcomes and cryptographic hashes. |

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

2. **Immutable Trace Sealing**:
   - Post-run execution of `agentv certify` computes a SHA3-256 digest over the raw `run.jsonl`.
   - The resulting hash is signed using Ed25519 (`system_id` or enterprise KMS/HSM).
   - Writes the `.sealed` sentinel marker. Any modification to `run.jsonl` breaks hash verification during `agentv verify` or release gate checks (`agentv gate`).

3. **Execution Truth Levels**:
   - Traces lacking explicit `execution_mode: "live"` or `"hybrid"` are stamped `provisional: true`.
   - Provisional runs can NEVER be certified as authoritative for enterprise compliance or safety attestations.

---

### B. For Agent Integrators
**Objective**: Build compliant agent adapters, manage multi-turn communication, and integrate tool calling and HITL workflows.

1. **Protocol Handshake & Routing**:
   - Adapters declare communication protocols (`http`, `local`, `socket`, `stdio`).
   - The harness emits `routing_resolved` with target endpoints before task execution.
   - At each turn, `step_start` logs the active protocol in the sequence ledger.

2. **Tool Execution Interface**:
   - When the agent responds with `action: "call_tool"`, the harness emits `tool_call` containing tool name and parameter arguments.
   - The sandbox executes the tool and emits `tool_result` with the structured return payload or error message.
   - The agent receives this output as an `environment` role message on the subsequent turn.

3. **Human-In-The-Loop (HITL) Interventions**:
   - If an agent attempts high-risk actions exceeding its policy delegation, it triggers `action: "hitl_pause"`.
   - The harness emits `hitl_pause`, suspending execution until an authorized human operator approves or rejects via the console or CLI.
   - Upon resolution, `hitl_resume` is emitted. If rejected, execution aborts and the node fails closed (`POLICY_DENIED`).

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
