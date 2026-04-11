---
title: Extender API Reference
description: Detailed reference for the AgentV Console REST API and internal core libraries.
---

The Extender API is designed for system integrators, dashboard developers, and platform engineers. It includes the Console REST API and the core libraries for orchestration and metrics.

## 🌉 Console REST API

When running `agentv console`, the harness launches a Flask-based REST API (default: `http://localhost:5000/api`).

### 🔐 Authentication & Permissions
Access is governed by the [Security Protocol](/ai-agent-eval-harness/auditor/security/).

- **`POST /api/auth/login`**: Authenticate via `DASHBOARD_API_KEY`. Sets an encrypted session cookie.
- **`GET /api/auth/handoff`**: Generates a short-lived (60s) JWT token for secure frontend-to-plugin communication.

### 📋 System & Navigation
- **`GET /api/info`**: Returns system status, engine version, and active 프로젝트 directories.
- **`GET /api/nav`**: Returns the dynamic sidebar registry. This reflects any navigation items injected by [Plugins](/ai-agent-eval-harness/extender/plugins/).

### 📂 Scenario Management
- **`GET /api/scenarios`**: Faceted search across the industrial scenario catalog.
- **`POST /api/scenarios`**: Saves or updates a scenario JSON file in the authoritative `industries/` directory. (Validated against the [Secure Jail](/ai-agent-eval-harness/auditor/security/)).

### ⚡ Execution & Monitoring
- **`POST /api/evaluate`**: Triggers an asynchronous evaluation run. Returns a `scenario_id` for tracking.
- **`GET /api/runs`**: Lists recent traces and individual attempt artifacts.

---

## 🛡️ Public Trust Protocol (v1)

These endpoints are unprotected by the primary API key to allow external deployment gates and CI/CD pipelines to verify results.

- **`GET /api/v1/certificates/<run_id>`**: Retrieves the authoritative [Verification Certificate](/ai-agent-eval-harness/auditor/trust-protocol/) (VC) for a specific run.
- **`GET /api/v1/verify/<run_id>`**: Performs real-time SHA-256 integrity verification of the trace against its VC.

---

## 📦 Core Library API (`eval_runner`)

### `engine.run_evaluation`
The primary entry point for orchestrating evaluations.

```python
async def run_evaluation(
    scenario: dict, 
    attempts: int = 1, 
    metadata: Optional[dict] = None
) -> Union[dict, list]
```

### `AgentAdapterRegistry`
Manage communication protocols (HTTP, Local, Socket, LangGraph, etc.).
```python
from eval_runner.engine import AgentAdapterRegistry
AgentAdapterRegistry.register("my-protocol", my_custom_adapter_func)
```

### `MetricRegistry`
The central registry for all evaluation markers.
```python
from eval_runner.metrics import MetricRegistry
metric_func = MetricRegistry.get("tool_call_correctness")
score = metric_func(expected_list, actual_list)
```

### `loader.load_scenario`
Authoritative scenario loader supporting local files and **Benchmark URIs** (`gaia://`, `assistantbench://`).
