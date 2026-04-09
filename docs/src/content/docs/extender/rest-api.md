---
title: Extender API Reference
description: API specification for building and registering platform extensions.
sidebar:
  order: 2
---
# Platform Extender API Reference

The Platform Extender API is designed for system integrators, dashboard developers, and platform engineers who want to build on top of the MultiAgentEval harness.

## 🌉 The Console REST API

When you run `multiagent-eval console`, the harness launches a Flask-based REST API (default: `http://localhost:5000/api`).

### 🔐 Authentication & Permissions

The API uses **Identity-Based PBAC (Permission-Based Access Control)**. 

#### `POST /api/auth/login`
Authenticates a user via an API Key.
- **Body**: `{"apiKey": "AEH-..."}`
- **Success**: Sets an encrypted session cookie and returns user metadata.

#### 🛠️ Programmatic Authorization (Headless)
For CI/CD and programmatic orchestration, you can bypass session state by providing the `X-Api-Key` header with Every request.

- **Header**: `X-Api-Key: {SERVICE_API_KEY}`
- **Note**: The harness prioritizes `SERVICE_API_KEY` for programmatic headers, falling back to `DASHBOARD_API_KEY` if not configured.

#### `GET /api/auth/handoff`
Generates a short-lived (60s) JWT handoff token for secure frontend-to-plugin communication.

---

### 📋 System & Metadata

#### `GET /api/info`
Returns the authoritative system status, including:
- Engine version.
- Count of active plugins, adapters, and environment shims.
- Configured agent endpoints (Gemini, Claude, Ollama).
- Active project directories (masked for security).

#### `GET /api/nav`
Returns the dynamic navigation registry. Extenders can inject items here via the `on_register_console_routes` hook.

---

### 📂 Scenario Management

#### `GET /api/scenarios`
Faceted search across the scenario catalog.
- **Query Params**: `q` (search string), `industry`, `difficulty`, `limit`, `page`.

#### `POST /api/scenarios`
Saves or updates a scenario JSON file in the authoritative `industries/` directory.
- **Body**: Complete AES V1.3 scenario JSON.
- **Security**: Validates against the project jail and sanitizes industry paths.

---

### ⚡ Execution & Monitoring

#### `POST /api/evaluate`
Triggers an asynchronous evaluation run.
- **Body**: `{"path": "scenarios/my_test.json", "max_turns": 5}`
- **Response**: `{"status": "started", "scenario_id": "..."}`
- **Note**: Runs in a background thread to prevent blocking the Console API.

#### `GET /api/runs`
Lists recent run traces, including both global logs and individual per-run artifacts.
- **Filtering**: Supports `q` param for searching by Run ID or Scenario Name.

---

### 🔌 Extensibility Hooks (Python)

Platform extenders can inject custom logic directly into the Console by implementing specific hooks in their plugins.

#### `on_register_console_routes(app, nav_registry)`
Called during Flask app initialization.
- `app`: The Flask application instance (for adding `@app.route`).
- `nav_registry`: The list of sidebar navigation items (for adding custom UI links).

**Example Interface:**
```python
class MyCustomDashboardPlugin:
    def on_register_console_routes(self, app, nav_registry):
        @app.route("/api/my-plugin/stats")
        def get_stats():
            return {"data": 42}
            
        nav_registry.append({
            "id": "my_plugin",
            "title": "Custom Stats",
            "path": "/my-plugin",
            "icon": "activity",
            "type": "internal"
        })
```

---

### 🛡️ Public Trust Endpoints (v1)

These endpoints are unprotected to allow external deployment gates to verify results.

- `GET /api/v1/certificates/<run_id>`: Industrial VC retrieval.
- `GET /api/v1/verify/<run_id>`: SHA-256 integrity verification.

