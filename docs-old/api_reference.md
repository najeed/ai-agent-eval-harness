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

### `GET /api/v1/doctor`
Roadmap (P1): Environmental health audit and project readiness check.
- **Permission**: `SCENARIOS_READ`
- **Security**: Protected

---

## 2. Evaluation & Orchestration

### `POST /api/v1/evaluate`
Triggers an asynchronous evaluation for a specific scenario or path.
- **Permission**: `EVAL_TRIGGER`
- **Security**: Protected
- **Body**: `{"path": "loan-scenario-v1", "max_turns": 10}`
  - *Note*: `path` acts as an alias. It first resolves against the **Scenario ID** in the catalog index. If no match is found, it expects a **project-relative path** (e.g., `industries/fin/scenarios/loan.json`).

### `POST /api/v1/mutate`
Roadmap (P0): Programmatic scenario mutation for variance testing.
- **Permission**: `SCENARIOS_READ`
- **Body**: `{"type": "typo", "path": "...", "raw_json": {...}}` (Supports raw content).

### `GET /api/v1/metrics`
Roadmap (P0): Lists all registered evaluation metrics.
- **Permission**: `SCENARIOS_READ`

### `GET /api/v1/taxonomy`
Roadmap (P0): Returns the failure taxonomy (AEH v1.5).
- **Permission**: `SCENARIOS_READ`

### `POST /api/v1/spec-to-eval`
Roadmap (P1): Converts Markdown PRDs to scenario JSON stubs.
- **Permission**: `SCENARIOS_READ`
- **Body**: `{"markdown": "...", "input_path": "..."}` (Supports raw content).

### `GET /api/v1/runs/<run_id>`
Returns the real-time status and metadata of a specific evaluation.
- **Permission**: `RUNS_READ`
- **Security**: Protected
- **Statuses**: `RUNNING`, `COMPLETED`, `NOT_FOUND`

### `GET /api/v1/explain/<run_id>`
Roadmap (P2): Forensic Root Cause Analysis (RCA) as a service.
- **Permission**: `RUNS_READ`

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
Resets the demo environment to its state.
- **Permission**: `DEMO_EXECUTE`
- **Security**: Protected
