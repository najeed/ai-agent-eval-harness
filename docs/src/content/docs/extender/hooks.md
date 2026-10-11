---
title: Lifecycle Hooks Reference
description: Authoritative reference for all AgentV plugin lifecycle hooks, interceptor pipelines, and event bus bridges.
---

Hooks are the primary mechanism for extending the AgentV evaluation engine without modifying core orchestration loops. AgentV provides two complementary hook mechanisms:

1. **Native Abstract Hooks**: Explicit interface methods defined on `eval_runner.plugins.BaseEvalPlugin` for lifecycle boundaries, interceptors, component discovery, and durable workflows.
2. **Dynamic Event Bus Bridge Hooks**: Auto-bridged hooks where any event emitted over the session `EventEmitter` triggers an `on_<event_name.lower()>(self, context, **event_data)` callback on loaded plugins.

---

## 1. 🏁 Global & Step Lifecycle Hooks

### `before_evaluation(self, context, span_context=None)`
- **Trigger**: Invoked immediately before the evaluation scenario begins execution.
- **Arguments**: `context: EvaluationContext`, `span_context: dict[str, Any] | None`
- **Use Case**: Initialize plugin state, establish connection pools, seed database mocks, or inject distributed tracing context.

### `after_evaluation(self, context, results, span_context=None)`
- **Trigger**: Invoked after all attempt iterations complete and terminal metrics are calculated.
- **Arguments**: `context: EvaluationContext`, `results: list[dict[str, Any]]`, `span_context: dict[str, Any] | None`
- **Use Case**: Export forensic artifacts, publish metrics to external telemetry collectors, or execute teardown operations.

### `on_step_start(self, context=None, node_id=None, node_data=None, **kwargs)`
- **Trigger**: Invoked when an execution graph DAG node or scenario step begins execution.
- **Arguments**: `context: EvaluationContext`, `node_id: str | None`, `node_data: dict[str, Any] | None`
- **Use Case**: Monitor node execution start, start task-scoped timer budgets, or set up task-specific virtual filesystem jail states.

### `on_step_end(self, context=None, node_id=None, verdict=None, **kwargs)`
- **Trigger**: Invoked when an execution graph DAG node completes evaluation.
- **Arguments**: `context: EvaluationContext`, `node_id: str | None`, `verdict: Any`
- **Use Case**: Capture intermediate step scores, assert transition invariants, or log failure taxonomy classifications.

---

## 2. 🛡️ Interception & Governance Hooks

Interceptors can observe, mutate, or reject operations before state transitions occur.

### `on_tool_request(self, context, tool_name, arguments=None)`
- **Trigger**: Invoked before any tool invocation is dispatched to a World Shim or external sandbox.
- **Arguments**: `context: EvaluationContext`, `tool_name: str`, `arguments: dict[str, Any] | None`
- **Return Contract**:
  - Return `True` to allow tool execution.
  - Return `False` to reject and fail the tool call.
  - Return a mutated `dict` to rewrite tool arguments dynamically.
- **Use Case**: Enforce parameter boundaries, redact secrets, prevent unauthorized shell executions, or implement rate limits.

### `on_before_commit(self, context, state_diff=None)`
- **Trigger**: Invoked before a state transition or VFS workspace modification is committed.
- **Arguments**: `context: EvaluationContext`, `state_diff: dict[str, Any] | None`
- **Return Contract**: Return `True` to allow commit; return `False` to abort and trigger compensating rollback.
- **Use Case**: Enforce enterprise compliance invariants before persistent state changes.

### `on_rollback(self, context, compensation_action=None)`
- **Trigger**: Invoked when executing a compensating rollback action following a transaction failure or DAG recovery.
- **Arguments**: `context: EvaluationContext`, `compensation_action: dict[str, Any] | None`
- **Return Contract**: Return `True` upon successful rollback; return `False` on failure.

---

## 3. 👥 Human-in-the-Loop (HITL) & Approval Hooks

### `on_approval_request(self, context, approval_data=None)`
- **Trigger**: Invoked when an agent requests a high-risk operation requiring human operator approval.
- **Arguments**: `context: EvaluationContext`, `approval_data: dict[str, Any] | None`
- **Return Contract**: Return `True` or a dict to proceed; return `False` to reject immediately.

### `on_approval_created(self, context, request)`
- **Trigger**: Invoked when a durable `ApprovalRequest` is generated and saved to the `ApprovalStore`.
- **Arguments**: `context: EvaluationContext`, `request: ApprovalRequest`
- **Use Case**: Dispatch notifications to Slack, PagerDuty, email, or an enterprise ticketing system.

### `on_approval_resolved(self, context, request)`
- **Trigger**: Invoked when an operator resolves an approval request (`APPROVED` or `REJECTED`).
- **Arguments**: `context: EvaluationContext`, `request: ApprovalRequest`
- **Use Case**: Log operator identity to forensic audit trail or release paused execution loops.

---

## 4. 📦 Artifact & Compliance Hooks

### `on_artifact_created(self, run_id, artifact_name, artifact_path, metadata=None)`
- **Trigger**: Invoked when an artifact (trace, certificate, or report) is committed to the `ArtifactStore` (SOC 2 CC6.8).
- **Arguments**: `run_id: str`, `artifact_name: str`, `artifact_path: str`, `metadata: dict[str, Any] | None`
- **Use Case**: Compute secondary SHA3-256 evidence digests, sync to immutable object storage, or mirror to external compliance logs.

---

## 5. 🔍 Component Discovery & Registration Hooks

### `on_register_commands(self, registry)`
- **Trigger**: Invoked during CLI initialization.
- **Use Case**: Register custom subcommands under `agentv`.

### `on_discover_adapters(self, registry)`
- **Trigger**: Invoked when initializing communication protocol adapters.
- **Use Case**: Register custom agent adapters (e.g. `myproto://`).

### `on_register_simulators(self, registry)`
- **Trigger**: Invoked during simulator registry bootstrapping.
- **Use Case**: Mount custom World Shims (e.g. proprietary databases, internal API emulators).

### `on_discover_metrics(self, registry)`
- **Trigger**: Invoked during evaluation metric discovery.
- **Use Case**: Register domain-specific assertions and scoring functions.

### `on_diagnose_failure(self, taxonomy)`
- **Trigger**: Invoked during failure triage initialization.
- **Use Case**: Register custom `BaseForensicAnalyzer` classes with the taxonomy engine.

### `on_register_console_routes(self, app, nav_registry)`
- **Trigger**: Invoked when the Visual Console (Flask) server initializes.
- **Use Case**: Register custom REST API blueprints and inject dynamic sidebar navigation tabs into the React dashboard.

---

## 6. ⚡ Dynamic Event Bus Bridge Hooks

In addition to native abstract hooks, the runtime session automatically bridges all `CoreEvents` from the central `EventEmitter` to loaded plugins:

```python
# Session automatically converts CoreEvents to plugin hooks:
# CoreEvents.TURN_START ("turn_start") -> on_turn_start(self, context, **event.data)
# CoreEvents.TOOL_CALL ("tool_call")   -> on_tool_call(self, context, **event.data)
```

### Common Event Bridge Signatures:
- `on_run_start(self, context, **data)`: Triggered on session start.
- `on_turn_start(self, context, turn, task_id, **data)`: Triggered on each conversational turn.
- `on_turn_end(self, context, turn, task_id, **data)`: Triggered when a turn completes.
- `on_tool_call(self, context, tool, arguments, **data)`: Triggered on sandbox tool invocation.
- `on_tool_result(self, context, tool, result, **data)`: Triggered on tool execution result.
- `on_external_tool_call(self, context, tool, arguments, source, **data)`: Triggered on remote agent tool ingestion.
- `on_external_tool_result(self, context, tool, result, receipt_hash, **data)`: Triggered on remote tool result ingestion.
- `on_hitl_pause(self, context, task_id, prompt, approval_id, **data)`: Triggered on human intervention pause.
- `on_hitl_resume(self, context, task_id, approved, **data)`: Triggered on resumption from human approval.
- `on_run_end(self, context, status, passed, score, **data)`: Triggered on final run completion.
