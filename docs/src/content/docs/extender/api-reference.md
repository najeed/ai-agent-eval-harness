---
title: Extender API Reference
description: Authoritative reference for the AgentV Console REST API and internal core libraries.
---

The Extender API is designed for system integrators, technology partners, dashboard developers, and platform engineers who want to build on or interact with the AgentV harness. It includes the Console REST API and the core `eval_runner` Python libraries.

## 🌉 Console REST API

When running `agentv console`, the harness launches a Flask-based REST API (default: `http://localhost:5000/api`). Access is governed by the [Security Protocol](/auditor/security/).

### 🔐 Authentication & Permissions

The API uses **Identity-Based PBAC (Permission-Based Access Control)**. 

#### `POST /api/auth/login`
Authenticates a user via an API Key.
- **Body**: `{"apiKey": "AEH-..."}`
- **Success**: Sets an encrypted session cookie and returns user metadata.

#### 🛠️ Programmatic Authorization (Headless)
For CI/CD and programmatic orchestration, bypass session state by providing the `X-Api-Key` header with every request.
- **Header**: `X-Api-Key: {SERVICE_API_KEY}`
- **Note**: The harness prioritizes `SERVICE_API_KEY` for programmatic headers, falling back to `DASHBOARD_API_KEY` if not configured.

#### `GET /api/auth/handoff`
Generates a short-lived (60s) JWT handoff token for secure frontend-to-plugin communication.

---

### 📋 System & Navigation

#### `GET /api/info`
Returns system status, including:
- Engine version and configuration metadata.
- Count of active plugins, adapters, and environment shims.
- Configured agent endpoints (Gemini, Claude, Ollama).
- Active project directories (masked for security).

#### `GET /api/nav`
Returns the dynamic navigation registry. Extenders can inject items here via the `on_register_console_routes` hook.

---

### 📂 Scenario Management

#### `GET /api/scenarios`
Faceted search across the industrial scenario catalog.
- **Query Params**: `q` (search string), `industry`, `difficulty`, `limit`, `page`.

#### `POST /api/scenarios`
Saves or updates a scenario JSON file in the `industries/` directory.
- **Body**: Complete AES V1.4 scenario JSON.
- **Security**: Validates against the project jail and sanitizes industry paths.

---

### ⚡ Execution & Monitoring (Industrial v1)

#### `POST /api/v1/evaluate`
Triggers an asynchronous evaluation run using the authoritative industrial namespace.
- **Method**: `POST`
- **Body**:
    - `path` (string, **required**): Absolute or relative path to the scenario JSON.
    - `max_turns` (int, optional): Maximum conversation depth (Default: 10).
- **Response**: `{"status": "started", "run_id": "eval_20240412_..."}`
- **Note**: initiates a background thread. Results are streamed to `runs/<run_id>/run.jsonl`. Enforces strict vault affinity.

#### `GET /api/v1/runs/<run_id>`
Industrial Polling Primitive.
- **Response**: Returns run status (`COMPLETED`, `RUNNING`), vault source, and file metadata.
- **Note**: Checks the authoritative vault first, falling back to the master log if the vault directory is missing.

#### `GET /api/runs`
Legacy faceted listing of all traces (supports master log and vault discovery).

---

### 🛡️ Public Trust Protocol (v1)

These endpoints live at the top-level `/v1/` namespace to clearly distinguish **Public Audit Services** (unprotected, read-only) from **Private Management APIs** (protected under `/api/`).

#### `POST /api/v1/certify`
Industrial Certification Service. Signs the trace zero-copy within the authoritative vault.
- **Body**: `run_id` (required), `identity`, `status`, `score`, `policy_ref`, `ttl`.
- **Note**: Requires write access to the vault. Generates `run_manifest.json`.

#### `GET /v1/certificates/<run_id>`
Retrieves the [Verification Certificate](/auditor/trust-protocol/) (VC) for a specific run. Unprotected for external deployment gates.

#### `GET /v1/verify/<run_id>`
Public Verification API for SHA-256 and cryptographic proof check. Performs a live integrity check comparing the `run.jsonl` trace against the issued manifest.

#### `GET /v1/identity/<identity_id>/public_key`
Resolves the public key for a forensic identity to support multi-party signature verification.

---

### 🔌 Extensibility Hooks (Python)

Platform extenders can inject custom logic directly into the Console by implementing specific hooks in their plugins.

#### `on_register_console_routes(app, nav_registry)`
Called during Flask app initialization.
- `app`: The Flask application instance (for adding `@app.route`).
- `nav_registry`: The list of sidebar navigation items (for adding custom UI links).

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
