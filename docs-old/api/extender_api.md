# Platform Extender API Reference

The Platform Extender API is designed for system integrators, dashboard developers, and platform engineers who want to build on top of the AgentV harness.

## 🌉 The Console REST API

When you run `agentv console`, the harness launches a Flask-based REST API (default: `http://localhost:5000/api`).

### 🔐 Authentication & Permissions

The API uses **Identity-Based PBAC (Permission-Based Access Control)**. 

#### `POST /api/auth/login`
Authenticates a user via an API Key.
- **Body**: `{"apiKey": "AEH-..."}`
- **Success**: Sets an encrypted session cookie and returns user metadata.

#### `GET /api/auth/handoff`
Generates a short-lived (60s) JWT handoff token for secure frontend-to-plugin communication.

---

### 📋 System & Metadata

#### `GET /api/info`
Returns the system status, including:
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
Saves or updates a scenario JSON file in the `industries/` directory.
- **Body**: Complete AES V1.3 scenario JSON.
- **Security**: Validates against the project jail and sanitizes industry paths.

---

#### `POST /api/v1/evaluate`
Triggers an asynchronous evaluation run using the authoritative industrial namespace.
- **Method**: `POST`
- **Body**:
    - `path` (string, **required**): Scenario ID alias or relative path to the scenario JSON.
    - *Note*: Priority resolution on **Scenario ID** via the catalog. If no match is found, it fallbacks to direct file resolution. Use `agentv list` to find IDs.
    - `max_turns` (int, optional): Maximum conversation depth (Default: 10).
- **Response**:
    ```json
    {"status": "started", "run_id": "eval_20240412_..."}
    ```
- **Note**: This endpoint initiates a background thread. Results are streamed to `runs/<run_id>/run.jsonl`. This endpoint enforces strict vault affinity.

#### `GET /api/v1/runs/<run_id>`
Industrial Polling Primitive.
- **Method**: `GET`
- **Params**: None.
- **Response**:
    ```json
    {
      "run_id": "...",
      "status": "COMPLETED",
      "source": "vault",
      "path": "runs/.../run.jsonl",
      "size": 12450,
      "mtime": 1712952000.0
    }
    ```
- **Note**: Checks the authoritative vault first, falling back to a shallow scan of the master log if the vault directory is missing or unlinked.

#### `GET /api/runs`
Legacy faceted listing of all traces (supports master log and vault discovery).
- **Method**: `GET`
- **Params**:
    - `q` (string, optional): Search filter for Run ID or Scenario Name.
- **Filtering**: Supports shallow string matching across the forensic registry.

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

- `POST /api/v1/certify`: Industrial Certification Service. Signs the trace zero-copy within the authoritative vault.
    - **Body**:
        - `run_id` (string, **required**): Unique identifier for the evaluation run.
        - `identity` (string, optional): Signing Identity (Default: `system_id`).
        - `status` (string, optional): Compliance outcome (e.g., `pass`, `fail`).
        - `score` (float, optional): Normalized evaluation score (0.0 - 1.0).
        - `policy_ref` (string, optional): Reference ID for the governing policy.
        - `ttl` (int, optional): Certificate validity in days.
    - **Response**: A complete VC v3 manifest containing the `sha256` hash and `provenance_chain`.
    - **Note**: This requires write access to the vault. It generates `run_manifest.json` in the run directory.
- `GET /v1/certificates/<run_id>`: Public Trust Protocol retrieval of the Verification Certificate (VC).
    - **Response**: The raw VC v3 JSON manifest.
    - **Note**: Unprotected endpoint for industrial deployment gates.
- `GET /v1/verify/<run_id>`: Public Verification API for SHA-256 and cryptographic proof check.
    - **Response**:
        ```json
        {
          "run_id": "...",
          "verified": true,
          "timestamp": "2024-04-12T...",
          "method": "ED25519 cryptographic signature proof"
        }
        ```
    - **Note**: Performs a live integrity check comparing the `run.jsonl` trace against the issued manifest.
