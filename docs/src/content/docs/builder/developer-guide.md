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

### Immutability
`EvaluationContext` and `TurnContext` are **frozen** dataclasses. Interceptors must use `dataclasses.replace` to propagate state changes.

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
| `on_register_console_routes`| Inject custom REST routes and navigation into the [Visual Console](/evaluator/user-manual/). |

---

## ⚖️ Metrics System

Metrics live in `eval_runner/metrics/` and are registered via the `MetricRegistry`.

### Registering a New Metric
```python
from eval_runner.metrics import MetricRegistry

@MetricRegistry.register("my_industrial_metric")
def my_metric(criterion, summary):
    # Logic to return 0.0 to 1.0
    return 1.0 if "success" in summary else 0.0
```

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
