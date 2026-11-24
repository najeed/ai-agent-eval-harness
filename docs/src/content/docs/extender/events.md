---
title: CoreEvents Reference
description: Authoritative guide to the AgentV Event Bus and Behavioral DNA hierarchy.
---

The AgentV event bus is the central nervous system of the evaluation harness. It facilitates decoupled communication between the engine, plugins, and forensic collectors.

## 🧬 Hierarchy of Behavioral DNA
Behavioral DNA markers allow the engine and agents to provide high-fidelity traces of their internal decision-making process.

| Level | Marker | Source | Description |
| :--- | :--- | :--- | :--- |
| **0** | `STRATEGY` | Engine | Mission-level intent (e.g., Pass@K, Consistency). |
| **1** | `PHASE` | Engine | Macro segments of the evaluation lifecycle. |
| **2** | `MANEUVER` | Engine | Orchestration logic for a specific workflow node. |
| **3** | `CHAIN` | Engine | A sequence of reasoning links within a task. |
| **4** | `NODE` | Engine | A single atomic reasoning/execution turn. |
| **5** | `SUBTASK` | Agent/Engine | Discrete logic units (e.g., "Dependency Check"). |
| **6** | `ACTION` | Agent | Individual tool decisions and reasoning leaps. |
| **7** | `STEP` | Agent | Atomic environment interactions. |

---

## 🏗️ Infrastructure Events
These events track the lifecycle of the evaluation run.

### `RUN_START` / `RUN_END`
- **Trigger**: Called when an evaluation mission starts or finishes.
- **`RUN_START` Payload**: `run_id`, `scenario_id`, `k_attempts`, `execution_mode`, `reproducibility_fingerprint`.
- **`RUN_END` Payload**: `run_id`, `status`, `passed`, `score`, `pass_at_k`, `attempt_statistics`, and mandatory `finalization` (`EvaluatorFinalizationRecord`).
- **Monotonic Terminal Boundary**: `run_end` is strictly the LAST event emitted. Intermediate strategy telemetry (`strategy_end`) must be dispatched *prior* to `run_end`. Emitting any event after `run_end` violates stream monotonicity and fails closed.

### `STRATEGY_START` / `STRATEGY_END`
- **Trigger**: Marks the exploration strategy lifecycle (e.g. `pass_at_k`). `strategy_end` concludes strategy telemetry before `run_end`.

### `PHASE_START` / `PHASE_END`
- **Trigger**: Demarcates the execution phase across all attempts (`phase="pass_at_k_execution"`).

### `EXECUTION_GRAPH_NODE` / `EXECUTION_GRAPH_EDGE`
- **Trigger**: Emitted by `WorkflowInterpreter` as DAG nodes activate, complete, or fail, and as typed edge predicates are evaluated.

### `PARALLEL_STATE_MERGED`
- **Trigger**: Emitted upon post-gather state merge when concurrent fork branches converge.

### `TASK_START` / `TASK_END`
- **Trigger**: Called when a specific task node within a scenario starts.
- **Payload**: `task_id`, `attempt`.

### `TURN_START` / `TURN_END`
- **Trigger**: Called for every interaction turn between the agent and environment.
- **Payload**: `turn`, `task_id`.

### `ROUTING_RESOLVED`
- **Trigger**: Emitted by `eval_runner/session.py` when capability-based routing discovers and binds protocol adapters and endpoints.
- **Payload**: `capabilities`, `resolved_protocol`, `resolved_endpoint`, `source`.

---

## 🛠️ Tool & Environment Events

### `TOOL_CALL` / `TOOL_RESULT`
- **Trigger**: Emitted when an agent executes a local/containerized tool inside the AgentV sandbox environment.
- **`TOOL_CALL` Payload**: `step`, `tool`, `arguments`, `provenance` (session sandbox events do not promise `call_id`).
- **`TOOL_RESULT` Payload**: `step`, `tool`, `result`, `provenance`. Error details are carried in the actual result payload.

### `EXTERNAL_TOOL_CALL` / `EXTERNAL_TOOL_RESULT`
- **Trigger**: Emitted when ingesting self-reported external agent execution trajectories from autonomous remote agent services.
- **Provenance Attributes**:
  - `source`: `"external_agent_telemetry"`
  - `provenance`: `"reported"`
  - `receipt_hash`: `"sha3_256:<hex>"` (deterministic digest computed over canonical RFC 8785 JSON representation of the call/result record).
- **Integrity Rule**: External telemetry receipts are strictly tracked and counted in `CertificationService` under `external_tool_calls_observed`, and are **never** relabeled as AgentV-sandbox-authoritative.

### `STATE_VERIFICATION`
- **Trigger**: Emitted when a state-parity check is performed.
- **Payload**: `metric`, `success`, `diff` (structural state difference).

### `STATE_READ` / `STATE_WRITE`
- **Trigger**: Emitted when an agent reads from or writes to the `SharedStateRegistry` (critical for taint tracking and data flow auditing).
- **Payload**: `agent`, `path`, `value`.

---

## 🔬 Forensic, Approval & Certification Events

### `HITL_PAUSE` / `HITL_RESUME`
- **Trigger**: `HITL_PAUSE` suspends execution when policy gates mandate manual human approval. `HITL_RESUME` resumes execution upon operator response.
- **Durable `HITL_PAUSE` Payload**: `task_id`, `prompt`, `approval_token`, `checkpoint_id`, `status="PAUSED_FOR_APPROVAL"`, `pause_start_ts`. Interactive HITL payloads can differ.
- **`HITL_RESUME` Payload**: `task_id`, `response`, `approved`.

### `APPROVAL_CREATED` / `APPROVAL_RESOLVED`
- **Trigger**: Emitted by `SessionApprovalManager` as durable approval requests are generated, persisted to the `ApprovalStore`, and resolved by human reviewers.
- **`APPROVAL_CREATED` Payload**: Serialized ApprovalRequest, including `approval_token`, `run_id`, `turn_index`, `outbound_payload_hash`, `status="PENDING"`, scope/digest, checkpoint/action metadata and timestamps. It is emitted before durable `hitl_pause` while the run remains writable.
- **`APPROVAL_RESOLVED` Payload**: Serialized ApprovalRequest with `decision` (`APPROVED`|`REJECTED`), `decided_by`, `decision_reason`, `decided_at`, and the original scope/action bindings.

### `TRACE_SEALED`

This constant is reserved; successful current certification commits certificate
and sealed provider lifecycle state without appending it to the completed trace.
Do not subscribe to it as a guaranteed certification-completion event.

### `CERTIFICATION_FAILED`
- **Trigger**: Emitted when post-run trace verification fails invariant checks (e.g. terminal boundary violation, state corruption, signature mismatch).
- **Payload**: `run_id`, `reason`, `code`.

### `PARITY_STATE_DIVERGENCE`
- **Trigger**: Emitted when transition-based world state differs from expected post-action assertions.
- **Payload**: `node_id`, `state_before_hash`, `state_after_hash`, `expected_diff`.

### `SANDBOX_EVENT`
- **Trigger**: Emitted during containerized sandbox lifecycle transitions.
- **Payload**: `action` (create/teardown/limit), `resource_id`.

---

## ⚡ Asynchronous Subscription & Concurrency

To prevent "eval-drag"—where intensive telemetry logging, compliance checking, or database updates slow down the agent's turn latency—AgentV's central `EventEmitter` supports asynchronous subscriber callbacks.

### Execution Modes
Default dispatch is synchronous (`ASYNC_EVENTS=false`). Required evidence sinks must acknowledge delivery and can fail the run; optional asynchronous telemetry is a separate path. The modes below apply when async dispatch is enabled.

1. **Asynchronous Coroutine Execution:** When an event is emitted within an active event loop, async subscriber callbacks are wrapped in task wrappers (`asyncio.create_task`) and run non-blockingly.
2. **Threaded Execution:** Synchronous subscriber callbacks are offloaded to an internal thread pool executor (`concurrent.futures.ThreadPoolExecutor`) to avoid blocking the main execution loop.

### OpenTelemetry Trace Propagation
The event system automatically captures and attaches the active OpenTelemetry tracing context (`otel_context`) to background execution threads and async tasks, ensuring parent-child span alignment is preserved across turn boundaries.

### Required evidence acknowledgement

Mandatory evidence subscribers run synchronously even with async telemetry
enabled. `emit_required()` requires an acknowledged sink; missing or failing
delivery raises EvidenceDeliveryError. The runner calls `finalize_capture()` to
reconcile emitted/acknowledged event counts and obtain provider completion before
certification. Waiting for optional subscribers does not establish that durable
capture is complete.

### Synchronization with `flush()`
Use `flush()` to wait for scheduled optional background callbacks. It does not replace mandatory evidence acknowledgement or `finalize_capture()`:

```python
from eval_runner.events import EventEmitter

# Emit event (schedules background tasks)
EventEmitter.get_global().emit("CUSTOM_COMPLIANCE_CHECK", {"run_id": "xyz"})

# Block until all scheduled background tasks complete
EventEmitter.get_global().flush(timeout=5.0)
```
