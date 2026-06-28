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
- **Trigger**: Called when a mission (multiple attempts) starts or finishes.
- **Payload**: `run_id`, `id`, `k_attempts`.

### `TASK_START` / `TASK_END`
- **Trigger**: Called when a specific task node within a scenario starts.
- **Payload**: `task_id`, `attempt`.

### `TURN_START` / `TURN_END`
- **Trigger**: Called for every interaction turn between the agent and environment.
- **Payload**: `turn`, `task_id`.

---

## 🛠️ Tool & Environment Events

### `TOOL_CALL`
- **Trigger**: Emitted when an agent requests a tool execution.
- **Payload**: `tool_name`, `arguments`.

### `TOOL_RESULT`
- **Trigger**: Emitted after a tool has executed.
- **Payload**: `tool_name`, `result`, `status` (success/error/policy_violation).

### `STATE_VERIFICATION`
- **Trigger**: Emitted when a state-parity check is performed.
- **Payload**: `metric`, `success`, `diff` (structural state difference).

### `STATE_READ`
- **Trigger**: Emitted when an agent reads a value from the `SharedStateRegistry`.
- **Payload**: `agent`, `path`, `value`.

### `STATE_WRITE`
- **Trigger**: Emitted when an agent successfully writes a value to the `SharedStateRegistry`.
- **Payload**: `agent`, `path`, `value` (Crucial for Taint Tracking).

---

## 🔬 Forensic Events

### `HITL_PAUSE`
- **Trigger**: Emitted when human intervention is requested.
- **Payload**: `agent_request`, `human_message`.

### `SANDBOX_EVENT`
- **Trigger**: Emitted during sandbox lifecycle transitions.
- **Payload**: `action` (create/teardown/limit), `resource_id`.

---

## ⚡ Asynchronous Subscription & Concurrency

To prevent "eval-drag"—where intensive telemetry logging, compliance checking, or database updates slow down the agent's turn latency—AgentV's central `EventEmitter` supports asynchronous subscriber callbacks.

### Execution Modes
1. **Asynchronous Coroutine Execution:** When an event is emitted within an active event loop, async subscriber callbacks are wrapped in task wrappers (`asyncio.create_task`) and run non-blockingly.
2. **Threaded Execution:** Synchronous subscriber callbacks are offloaded to an internal thread pool executor (`concurrent.futures.ThreadPoolExecutor`) to avoid blocking the main execution loop.

### OpenTelemetry Trace Propagation
The event system automatically captures and attaches the active OpenTelemetry tracing context (`otel_context`) to background execution threads and async tasks, ensuring parent-child span alignment is preserved across turn boundaries.

### Synchronization with `flush()`
If an evaluation session or test requires waiting for all scheduled asynchronous subscriber actions to complete (for example, to write final audit trails before terminating the runner process), invoke `events.flush()`:

```python
from eval_runner.events import EventEmitter

# Emit event (schedules background tasks)
EventEmitter.get_instance().emit("CUSTOM_COMPLIANCE_CHECK", {"run_id": "xyz"})

# Block until all scheduled background tasks complete
EventEmitter.get_instance().flush(timeout=5.0)
```
