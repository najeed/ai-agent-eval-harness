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
- **Security & Rate Limiting**: Enforces a sliding-window IP rate limit of 10 attempts per minute per remote IP. Returns HTTP 429 (`Too Many Requests`) if exceeded.
- **Session Security**: Sets an encrypted session cookie flagged with `HttpOnly`, `SameSite=Lax`, and `Secure` (in production).
- **Graceful Fallback**: If unauthenticated, the console enables a dismissable modal falling back to a read-only `Viewer` role for non-blocking exploration.

#### 🛠️ Programmatic Authorization (Headless)
For CI/CD and programmatic orchestration, bypass session state by providing the `X-Api-Key` or `Authorization: Bearer <key>` header with every request.
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

#### `GET /api/ping`
Public diagnostic health check. Returns system availability status.

---

### 📂 Scenario Management

#### `GET /api/scenarios`
Faceted search across the industrial scenario catalog.
- **Query Params**: `q` (search string), `industry`, `difficulty`, `limit`, `page`.

#### `POST /api/scenarios`
Saves or updates a scenario JSON file in the `industries/` directory.
- **Body**: Complete AES V1.4 scenario JSON.
- **Security**: Validates against the project jail and sanitizes industry paths.

#### `POST /api/scenarios/<scenario_id>/transition`
Enforces formal lifecycle state transitions for audited scenarios.
- **Path Param**: `scenario_id` (string).
- **Body**:
  - `transition` (string, **required**): Target transition name (`validate`, `ready`, `publish`, `deprecate`).
  - `reason` (string, **required**): Mandatory audit explanation justifying the lifecycle state change.
- **Legal State Machine Transitions**:
  - `Draft` $\rightarrow$ `Validated` $\rightarrow$ `Ready` $\rightarrow$ `Published` $\rightarrow$ `Deprecated`.
- **Response**: `{"status": "ok", "scenario_id": "...", "lifecycle_state": "Published"}`.

#### `GET /api/scenarios/readiness`
Four-state fail-closed execution readiness adjudication.
- **Query Param**: `scenario_id` (string, optional).
- **Adjudicated States**:
  - `BLOCKED`: Unauthenticated target, unreachable endpoint, or invalid scenario DAG.
  - `READY_TO_EXECUTE`: Configuration verified; ready for initial execution.
  - `READY_TO_CERTIFY`: Execution completed with clean trace logs; ready for cryptographic certification.
  - `CERTIFIABLE`: Passed all mandatory policy assertions, oracles, and evidence checks.

---

### ⚡ Execution & Monitoring (Industrial v1)

#### `POST /api/v1/evaluate`
Triggers an asynchronous evaluation run using the industrial namespace.
- **Method**: `POST`
- **Body**:
    - `path` (string, **required**): Scenario ID alias (e.g., `loan_risk`) OR a project-relative path (e.g., `industries/finance/scenarios/loan_approval_risk_check.json`).
    - *Note*: `path` acts as an alias. It first resolves against the **Scenario ID** in the catalog index. If no match is found, it expects a project-relative path. Use `agentv list` to verify IDs.
    - `max_turns` (int, optional): Maximum conversation depth (Default: 10).
- **Response**: `{"status": "started", "run_id": "eval_20240412_..."}`
- **Note**: Initiates a background thread. Results are streamed to `runs/<run_id>/run.jsonl`. Enforces strict vault affinity.

#### `POST /api/v1/mutate`
Programmatic scenario mutation for variance testing across the 3D Mutation Taxonomy.
- **Body**: `type` (mutation vector/operation), `path` (file path), or `raw_json` (raw object).

#### `GET /api/v1/metrics`
Discovery service for all registered evaluation metrics.

#### `GET /api/v1/taxonomy`
Retrieves the Industrial Failure Taxonomy (AEH v1.5).

#### `POST /api/v1/spec-to-eval`
Converts Markdown PRDs into validated scenario JSON stubs.
- **Body**: `markdown` (text) or `input_path` (file).

#### `GET /api/v1/doctor`
Environmental health audit and project readiness check.

#### `GET /api/v1/explain/<run_id>`
Forensic Root Cause Analysis (RCA) as a service.

#### `GET /api/v1/runs/<run_id>`
Industrial Polling Primitive.
- **Response**: Returns run status (`COMPLETED`, `RUNNING`), vault source, and file metadata.
- **Note**: Checks the vault first, falling back to the master log if the vault directory is missing.

#### `GET /api/runs`
Legacy faceted listing of all traces (supports master log and vault discovery).

#### `GET /api/v1/evidence/packages/<run_id>`
Downloads the single-file immutable `.agentv-package.json` package bundle containing the complete scenario, execution manifest, trace hashes, and assertion verdicts.

---

### 🛡️ Public Trust Protocol (v1)

These endpoints live at the top-level `/v1/` namespace to clearly distinguish **Public Audit Services** (unprotected, read-only) from **Private Management APIs** (protected under `/api/`).

#### `POST /api/v1/certify`
Industrial Certification Service. Executes an atomic two-phase prepare-verify-promote-seal transaction lifecycle.
- **Body**:
  - `run_id` (string, **required**): Unique identifier of the completed evaluation run.
  - `identity` (string, optional): Signing principal identity (defaults to authenticated caller or local trust root).
  - `policy_ref` (string, optional): Regulatory policy reference ID.
  - `ttl` (int, optional): Certificate time-to-live in seconds.
- **Cryptographic Trust Boundary**:
  - Caller-supplied overrides on `status` and `score` are strictly prohibited.
  - The verdict (`CERTIFIED`, `FAILED`) and compliance score are extracted server-authoritatively from terminal execution events (`run_end`, `session_decision`, `evaluation_result`).
- **Atomic Two-Phase Commit**:
  - Persists intermediate certification manifest (`_persist`).
  - Verifies signature, scenario binding, and oracle passing outcomes (`_verify`).
  - Promotes certificate to public vault (`_promote`).
  - Applies irreversible trace seal as final step (`_seal`). In case of verification error, automatically rolls back state (`_rollback`).

#### `GET /v1/certificates/<run_id>`
Retrieves the [Verification Certificate](/auditor/trust-protocol/) (VC v3) for a specific run. Unprotected for external deployment gates.

#### `GET /v1/verify/<run_id>`
Public Verification API for SHA3-256 and cryptographic proof check. Performs a live integrity check comparing the `run.jsonl` trace against the issued manifest using pure RFC 8785 JSON Canonicalization Scheme (JCS).

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

### `eval_runner.llm_resilience`
Centralized LLM Error Classifier and full-jitter exponential backoff retry wrapper.

```python
from eval_runner.llm_resilience import (
    execute_with_resilience,
    LLMRateLimitError,
    LLMQuotaExceededError,
    LLMAuthenticationError,
    LLMTransientError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
)

# Resilient asynchronous LLM call with jittered backoff
response = await execute_with_resilience(
    coro_fn=lambda: client.chat(prompt),
    provider="gemini",
    max_retries=3,
    initial_delay=1.0,
    max_delay=60.0,
)
```

### `eval_runner.mutation_algebra`
3D Mutation Taxonomy contracts and composable combinators.

```python
from eval_runner.mutation_algebra import (
    MutationCoordinate,
    MutationVector,
    MutationOperation,
    MutationTier,
    sequence,
    repeat,
    probability,
    after_event,
)

# Compose algebraic mutation pipeline
composite_mutator = sequence(
    [
        mutator_state_tamper,
        after_event("user_prompt", mutator_adversarial_injection),
        probability(0.5, mutator_schema_drift),
    ]
)
```

### `AgentAdapterRegistry`
Manage communication protocols (HTTP, SSE, Local, Socket, etc.) with dynamic lazy imports.
- **Protocols**: `http`, `sse` (Streaming), `local` (CLI), `socket` (Raw TCP), `gemini`, `openai`, `claude`, `grok`, `ollama`.
- **Standardized Signature**: Adapters must accept `(payload, endpoint=None)`.
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

---

## 🏛️ Public Runtime Extension Interface (`agentv_runtime`)

The `agentv_runtime.interfaces` and `agentv_runtime.reference` packages expose the authoritative abstract base classes and OSS reference implementations:

```python
import agentv_runtime
from agentv_runtime.canonical import canonical_json_dumps, canonical_json_bytes
from agentv_runtime.interfaces import (
    ArtifactStore,
    AuthorizationBackend,
    AuthPrincipal,
    CatalogStore,
    CheckpointStore,
    ExecutionBackend,
    LeaderboardStore,
    PolicyEvaluator,
    PolicyEvaluationResult,
    RunStore,
    SigningBackend,
)
from agentv_runtime.reference import (
    BasicFieldPolicyEvaluator,
    InProcessExecutionBackend,
    LocalEd25519SigningBackend,
    LocalFileArtifactStore,
    LocalFileCatalogStore,
    LocalFileLeaderboardStore,
    LocalFileRunStore,
    LocalLeaderboardStore,
    NullSigningBackend,
    PQCSigningBackend,
    SimpleAPIKeyAuthBackend,
    SQLiteCheckpointStore,
)

# RFC 8785 JSON Canonicalization Scheme (JCS)
canonical_bytes = canonical_json_bytes({"b": 1, "a": [2, 3]})

# Authoritative Contract Version Dunders
assert agentv_runtime.__runtime_api_version__ == "2.0"
assert agentv_runtime.__plugin_api_version__ == "1.0"
assert agentv_runtime.__config_schema_version__ == "1.0"
assert agentv_runtime.__aes_schema_version__ == "1.4"
assert agentv_runtime.__certificate_schema_version__ == "3.0.0"
assert agentv_runtime.__event_schema_version__ == "1.0"
```

See the [Public Extension Families Guide](/extender/extension-families/) for complete implementation specifications.

---

## ⚙️ Configuration Resolution (`ConfigResolver`)

AgentV resolves execution configuration across a deterministic 4-tier hierarchy:
1. **OSS Baseline Defaults**: Default directories and execution profiles.
2. **Configuration Files**: `.aes/config/*.d`, `config.json`, or YAML profiles.
3. **Environment Overrides**: Variables prefixed with `AGENTV_` / `AEH_`.
4. **Explicit Runtime Overrides**: Parameters supplied programmatically to `ConfigResolver.resolve()`.

```python
from eval_runner.config_resolver import ConfigResolver, ResolvedRuntimeConfig

resolved_cfg: ResolvedRuntimeConfig = ConfigResolver.resolve(
    explicit_overrides={"timeout_seconds": 180, "audit_level": 2}
)
print("Config Hash (SHA3-256):", resolved_cfg.config_hash)
```

