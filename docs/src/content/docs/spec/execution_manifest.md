---
title: "Execution Manifest & Canonical Execution Graph Specification"
description: "Authoritative specification for the ExecutionManifest contract, Canonical Execution Graph schema, and server-authoritative lifecycle state machine."
---

The **ExecutionManifest** (`agentv_runtime.manifest.ExecutionManifest`) and **Canonical Execution Graph** (`runs.schema.json`) define the single source of truth for evaluation runs and observed execution topologies in AgentV.

```mermaid
graph TD
    AES["📄 Scenario (AES v1.4 DAG)"]
    AgentCfg["🤖 Agent Target Config"]
    Tenant["🏢 Tenant & Workspace Context"]

    Builder["ManifestBuilder.build()"]
    Manifest["🔒 ExecutionManifest (SHA3-256)"]
    
    Exec["SessionManager Execution Loop"]
    GraphNodes["execution_graph_node Events"]
    GraphEdges["execution_graph_edge Events"]
    Cert["Verification Certificate (VC v3)"]

    AES --> Builder
    AgentCfg --> Builder
    Tenant --> Builder
    Builder --> Manifest
    Manifest --> Exec
    Exec --> GraphNodes
    Exec --> GraphEdges
    Exec --> Cert
```

---

## 1. ExecutionManifest Contract Schema

The manifest is defined in [`agentv_runtime.manifest`](file:///agentv_runtime/manifest.py) as an immutable dataclass (`@dataclass(frozen=True)`):

```python
@dataclass(frozen=True)
class ExecutionManifest:
    manifest_id: str  # Format: "man_{scenario_id}_{sha3_256[:12]}"
    scenario_id: str  # Unique scenario identifier
    scenario_version: str  # Scenario semantic version (e.g., "1.0.0")
    scenario_hash: str  # SHA3-256 hash of canonical scenario JSON payload
    tenant_id: str = "default"  # Multi-tenant isolation boundary
    workspace_id: str = "default"  # Workspace partition within tenant
    agent_config: dict[str, Any]  # Target endpoint, model, protocol, headers
    runtime_config: dict[str, Any]  # Max turns, timeouts, sandbox flags
    environment: dict[str, Any]  # Sealed environmental snapshot
    created_at: str  # ISO 8601 UTC timestamp
    created_by: str = "system"  # Authenticated principal ID
    metadata: dict[str, Any]  # Arbitrary tags and execution context
```

### Deterministic Integrity Hashing & Binding Formulas

AgentV computes all cryptographic hashes over canonical UTF-8 bytes using pure **RFC 8785 JSON Canonicalization Scheme (JCS)** (`agentv_runtime.canonical.canonical_json_dumps`):

$$\text{Scenario Hash} = \text{SHA3-256}\left(\text{RFC8785\_JCS}\left(\text{ScenarioPayload}\right)\right)$$

$$\text{Manifest Hash} = \text{SHA3-256}\left(\text{RFC8785\_JCS}\left(\text{ExecutionManifest}\right)\right)$$

During verification (`TraceVerifier.verify_trace_certificate` or `verify_package_artifacts`), the verifier recomputes $\text{Scenario Hash}$ directly from the executed scenario payload using `compute_scenario_hash()` and asserts exact equality against the manifest. If the scenario has drifted or was modified post-execution, the verification immediately fails with `UNVERIFIED`.

### Atomic Two-Phase Lifecycle Commit

To ensure non-repudiation, the execution manifest participates in an atomic four-stage transaction lifecycle:
1. **Prepare (`_persist`)**: Manifest, raw trace, and evidence ledger are written into an isolated staging location.
2. **Verify (`_verify`)**: In-memory cryptographic verification confirms trace seal integrity, evidence root hashes, and required oracle verdicts.
3. **Promote (`_promote`)**: Verified artifacts are promoted atomically to the authoritative public vault.
4. **Seal (`_seal`)**: Irreversible detached signature is applied. Any failure during stages 1–3 triggers an automatic rollback (`_rollback`), ensuring no corrupt or unverified manifests are ever published.

---

## 2. Canonical Execution Graph Data Model (`runs.schema.json`)

The execution graph formalizes observed execution topologies, multi-attempt retries, and branching workflows:

### Canonical Identity Model:
- **`scenario_node_id`** *(string, primary key)*: The immutable node ID from the Scenario DAG (e.g., `step_1_credit_pull`).
- **`execution_instance_id`** *(string)*: Per-attempt instance identifier formatted as `{scenario_node_id}:attempt:{attempt_number}`.
- **`parent_execution_id`** *(string, optional)*: Lineage pointer tracking retries or parent subtask dependencies.

### Event Schema 1: `execution_graph_node`
Emitted as each graph step transitions:
```json
{
  "event": "execution_graph_node",
  "scenario_node_id": "step_1_credit_pull",
  "execution_instance_id": "step_1_credit_pull:attempt:1",
  "node_type": "sequential",
  "status": "success",
  "duration_ms": 420.5,
  "attempt": 1,
  "max_attempts": 3,
  "failure_category": null,
  "metadata": {
    "tool_calls_count": 1,
    "tokens_consumed": 280
  },
  "timestamp": "2026-08-26T01:00:00.000Z"
}
```

### Event Schema 2: `execution_graph_edge`
Emitted to declare topological transitions between steps:
```json
{
  "event": "execution_graph_edge",
  "from_scenario_node_id": "step_1_credit_pull",
  "to_scenario_node_id": "step_2_risk_decision",
  "edge_type": "conditional",
  "condition_expression": "step_1_credit_pull.status == 'success'",
  "traversed": true,
  "metadata": {},
  "timestamp": "2026-08-26T01:00:00.500Z"
}
```

---

## 3. Two-Tier Status Architecture & Execution Readiness

### Execution & Governed States
| Layer | Attribute | Possible States | Meaning |
| :--- | :--- | :--- | :--- |
| **Tier 1 (Technical)** | `execution_status` | `QUEUED`, `RUNNING`, `EXECUTION_COMPLETED`, `EXECUTION_FAILED`, `STALLED` | Technical execution lifecycle of the runner and sandbox. |
| **Tier 2 (Governed)** | `verification_decision` | `VERIFIED`, `NOT_VERIFIED`, `POLICY_BREACH`, `UNVERIFIED` | Mathematical & cryptographic policy adjudication outcome. |

### Four-State Fail-Closed Readiness (`ReadinessState`)
Before initiating execution or issuing a cryptographic certificate, the engine adjudicates readiness across four fail-closed states:

1. **`BLOCKED`**: The agent endpoint is unreachable, unauthenticated, or the scenario graph is structurally malformed. All execution attempts immediately fail closed.
2. **`READY_TO_EXECUTE`**: Target configuration, environment shims, and scenario DAG are verified; ready for initial execution loop.
3. **`READY_TO_CERTIFY`**: Execution completed successfully with valid append-only `run.jsonl` traces; ready for cryptographic verification pass.
4. **`CERTIFIABLE`**: All required oracles, behavioral assertions, and hash bindings have passed, permitting irreversible detached signature application.
