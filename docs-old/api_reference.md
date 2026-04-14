# API Reference: Industrial REST Protocol

The Advanced AgentV Harness provides a high-fidelity REST API for orchestration, forensic auditing, and CI/CD integration. Access is governed by the **Identity Manager** using PBAC (Permission-Based Access Control) nodes.

## Authentication
Programmatic access is controlled via the `X-Api-Key` header.
- **Service Access**: Define `SERVICE_API_KEY` in your environment.
- **Dashboard Access**: Define `DASHBOARD_API_KEY` for UI-bridged workflows.

---

## 1. Core System & Telemetry

### `GET /api/info`
Returns consolidated system health, versioning, and telemetry.
- **Permission**: `SCENARIOS_READ`
- **Security**: Protected

### `GET /api/ping`
Liveness check for the dashboard and API engine.
- **Security**: Public (v1.5.0 verified)

### `POST /api/cleanup-runs`
Prunes historical traces and rotates log artifacts.
- **Permission**: `DEMO_EXECUTE`
- **Security**: Protected

---

## 2. Evaluation & Orchestration

### `POST /api/v1/evaluate`
Triggers an asynchronous evaluation for a specific scenario or path.
- **Permission**: `EVAL_TRIGGER`
- **Security**: Protected
- **Body**: `{"path": "industries/fin/scenarios/loan.json", "max_turns": 10}`

### `GET /api/v1/runs/<run_id>`
Returns the real-time status and metadata of a specific evaluation.
- **Permission**: `RUNS_READ`
- **Security**: Protected
- **Statuses**: `RUNNING`, `COMPLETED`, `NOT_FOUND`

### `GET /api/runs`
Lists historical run traces with faceted filtering.
- **Permission**: `RUNS_READ`
- **Security**: Protected

---

## 3. Trust & Verification (Public Protocol)

### `GET /v1/certificates/<run_id>`
Retrieves the Verification Certificate (VC) for a specific run.
- **Security**: **Public** (Industrial Trust Anchor)

### `GET /v1/verify/<run_id>`
Autonomous integrity verification: Checks a trace against its signed manifest.
- **Security**: **Public**

### `GET /v1/identity/<identity_id>/public_key`
Resolves the PEM-encoded public key for a forensic identity.
- **Security**: **Public**

### `POST /api/v1/certify`
Issues a cryptographically signed Verification Certificate (VC) for a completed run.
- **Permission**: `CERTIFY_WRITE`
- **Security**: Protected

---

## 4. Scenario Specification & Management

### `GET /api/scenarios`
Lists available scenarios with keyword and industry filtering.
- **Permission**: `SCENARIOS_READ`
- **Security**: Protected

### `POST /api/scenarios`
Saves or updates a scenario JSON file in the industry registry.
- **Permission**: `SCENARIOS_WRITE`
- **Security**: Protected

### `POST /api/scenarios/refresh`
Manually rebuilds the global scenario catalog index.
- **Permission**: `INDEX_REFRESH`
- **Security**: Protected

---

## 5. Visual Debugger & Documentation

### `GET /api/debugger/state?run_id=<run_id>`
Retrieves or streams the latest trajectory events for a specific run.
- **Permission**: `DEBUG_READ`
- **Security**: Protected

### `GET /api/nav`
Retrieves the dynamic UI navigation registry.
- **Permission**: `SCENARIOS_READ`
- **Security**: Protected

### `GET /api/docs`
Lists available guides and internal technical documentation.
- **Permission**: `DOCS_READ`
- **Security**: Protected

### `GET /api/docs/<path>`
Reads the content of a specific documentation markdown file.
- **Permission**: `DOCS_READ`
- **Security**: Protected

---

## 6. Industrial Demo (Jailed)

### `POST /api/demo/execute`
Executes whitelisted CLI commands within the demo jail.
- **Permission**: `DEMO_EXECUTE`
- **Security**: Protected (Hardened Subprocess)

### `POST /api/demo/reset`
Resets the demo environment to its authoritative state.
- **Permission**: `DEMO_EXECUTE`
- **Security**: Protected
