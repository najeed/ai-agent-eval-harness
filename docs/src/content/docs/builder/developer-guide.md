---
title: Developer Guide
description: Core architecture, internals, and extension patterns for AgentV engineers.
---

This guide is for engineers building on or extending the AgentV harness.

## 📂 Repository Architecture

- **`eval_runner/`**: The core Python package. Includes the engine, loaders, metrics, and simulators.
- **`industries/`**: The industrial scenario library.
- **`.aes/`**: **[NEW]** Authoritative configuration mesh (Shims, Adapters, Forensics).
- **`reports/`**: Destination for generated HTML and JSON results.
- **`runs/`**: The "Flight Recorder" storage for `.jsonl` execution traces.
- **`tests/`**: Unit and integration test suites.

---

## 🧠 Core Engine (Zero-Touch)

The engine is built on a decoupled, event-driven architecture to support enterprise-grade extensibility.

### Key Components
1.  **Runner (`runner.py`)**: Entry point for execution loops and multi-attempt (`pass@k`) logic.
2.  **SessionManager (`session.py`)**: Individual attempt state, trajectory tracking, and tool execution.
3.  **AgentAdapterRegistry**: Dynamic discovery of agent protocols (`http`, `langgraph`, `crewai`, etc.).
4.  **ToolSandbox**: Managed execution environment with workspace lifecycle management.
5.  **VerificationService (`verifier.py`)**: Manages `TraceVerificationInterceptor` chains for trace signing and validation.
6.  **ToolSandboxService (`tool_sandbox.py`)**: Context-isolated registry for `ToolSandboxInterceptor` execution filters.
7.  **MutationService (`mutator.py`)**: Manages `ScenarioMutator` chains for adversarial scenario variant generation.

### Immutability & Context Safety
*   `EvaluationContext` and `TurnContext` are **frozen** dataclasses. Interceptors must use `dataclasses.replace` to propagate state changes.
*   **Asynchronous Isolation**: `ToolSandboxService` leverages `contextvars.ContextVar` to secure coroutine-local state, ensuring concurrent evaluations remain safely isolated.
*   **Testing Helpers**: Pipeline services provide temporary override context managers (`override_interceptor` / `override_provider`). These temporarily activate a mock or custom interceptor/provider and guarantee clean, atomic state restoration on exit:
    ```python
    # Overriding sandbox executions for testing:
    with tool_sandbox_service.override_interceptor(my_mock_interceptor):
        result = sandbox.execute("git", {"args": ["status"]})

    # Overriding mutations temporarily:
    with mutation_service.override_provider(my_custom_mutator):
        mutated = mutate_scenario(scenario, "custom_mode")
    ```

---

## 🔌 Plugin System

Plugins are the primary extension point for the harness.

### Lifecycle Hooks
| Hook | Purpose |
| :--- | :--- |
| `before_evaluation` | Global setup and configuration validation. |
| `on_agent_turn_start`| Intercept and inspect context before the agent speaks. |
| `on_tool_request` | **Interception**: Return `False` to block a suspicious tool call. |
| `on_metrics_calculated`| Post-process scores or inject custom logic. |
| `on_register_commands`| Register custom namespaced CLI commands under `agentv plugin <name>`. |
| `on_register_simulators`| Inject custom environment World Shims into the simulator cache. |
| `on_register_console_routes`| Inject custom REST routes and navigation into the [Visual Console](/evaluator/user-manual/). |

---

## ⚖️ Metrics System

Metrics live in `eval_runner/metrics/` and are registered via the `MetricRegistry`.

### Registering a New Metric
```python
from eval_runner.metrics import MetricRegistry

@MetricRegistry.register("my_industrial_metric", source="EXTERNAL_PLUGIN")
def my_metric(criterion: dict, agent_summary: str, turns_taken: int) -> float:
    # Logic to return 0.0 to 1.0
    if turns_taken > 5:
        return 0.5
    return 1.0 if "success" in agent_summary else 0.0
```

### Parameter Introspection & Fulfillments
The core engine evaluates metrics using dynamic dispatch. It inspects your metric function's signature and automatically satisfies requested parameters. Available parameters include:
*   `criterion` / `eval_context`: The specific assertion metadata.
*   `agent_summary` / `summary` / `actual`: The agent's final text answer.
*   `conversation_history` / `history`: Deep-copied list of trajectory turns.
*   `used_tools` / `actual_tools`: List of tools execution trace.
*   `turns_taken`: Number of steps executed in this run.

---

## 🛡️ Sandbox & Workspace Lifecycle

The `ToolSandbox` ensures that each evaluation run has a clean, isolated environment.
- **`setup()`**: Initializes a fresh directory under `workspaces/`.
- **`teardown()`**: Performs cleanup unless `cleanup_workspace` is set to `false` in scenario metadata for forensic retrieval.

---

## 🔐 Security & Integrity

The harness uses an **ED25519 asymmetric signing protocol** for non-repudiable audit trails.
- **Key Storage**: Keys are stored in `.aes/keys/`.
- **Manifests**: Every run generates a signed `audit_manifest.json`.
- **Gating**: Use `agentv gate` in the CI/CD pipeline to enforce signature verification.

### WORM Audit Trail Sealing
For enterprise verification, AgentV writes cryptographic hashes to a Write-Once-Read-Many (WORM) log file named `audit_chain.jsonl` in the run trace directory. 
*   **Sign-on-turn**: Every tool call and state change appended to the execution trace is immediately signed and chained to the previous turn's hash.
*   **Interceptors**: Interceptors registered under `TraceVerificationInterceptor` can securely decorate this chain (e.g. logging to external Ledger nodes or cloud vaults) in real-time.
