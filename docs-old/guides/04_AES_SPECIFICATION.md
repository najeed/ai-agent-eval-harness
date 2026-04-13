# Guide: Agent Eval Specification (AES) v1.4

AES is the foundational standard for shareable, deterministic agent benchmarks.

## 1. Design Philosophy
- **Human Readable**: YAML-based for easy editing.
- **Framework Agnostic**: Works with LangGraph, CrewAI, or custom agents.
- **CI Ready**: Validatable via JSON Schema.
- **Deterministic DAGs**: Support for non-linear workflow execution with dependency gating.

## 2. Core Components (v1.4)

### Metadata (metadata)
AES v1.4 introduces a stricter metadata schema to ensure cross-platform reproducibility and forensic traceability:
- **`id`**: (Required) Global unique forensic identifier.
- **`capabilities`**: (Required) A list of specific agentic skills required (e.g., `web_navigation`, `sql_generation`).
- **`standards_registry`**: (Optional) Industry-standard identifiers (e.g., `ISO_20022`) for regulatory mapping.
- **`aes_version`**: Must be set to `1.4`.

### DAG-Based Execution (workflow)
Scenarios define a directed acyclic graph (DAG) of `nodes` and `edges`, enabling complex multi-stage evaluations with dependency tracking.

```yaml
workflow:
  nodes:
    - id: "task-1"
      task_description: "Initial credit check"
    - id: "task-2"
      task_description: "Policy enforcement audit"
  edges:
    - from: "task-1"
      to: "task-2"
```

### Typed Outcomes
Mandates adherence to industrial gold standards using typed result schemas.

### Pluralistic Judging (IJA)
Implements Inter-Judge Agreement metrics. Critical evaluations require a "Judge Panel" consensus.

### Externalized Mock Datasets
High-fidelity sector labs (e.g., Bank, EHR/HL7) load mock data dynamically from the `industries/` directory.

## 3. Infrastructure Hooks
- `pre_eval`: Command run before evaluation starts.
- `post_eval`: Command run after completion.

## 4. Environment & World Shims (First-Class Member)
Scenarios can declare which World Shims (environment simulators) they require.

- If `enabled_shims` is **omitted**, all 20 built-in shims are available by default.
- Shim keys correspond to the registry keys defined in `eval_runner/simulators.py`.

**Available built-in shim keys:** `git`, `api`, `database`, `slack`, `crm`, `email`, `calendar`, `jira`, `cloud`, `terminal`, `stripe`, `erp`, `browser`, `kb`, `support`, `social`, `vector`, `cicd`, `iot`, `security`

📖 See the full shim reference with per-shim actions and failure modes: [`docs/guides/help/07_WORLD_SHIMS_REFERENCE.md`](./help/07_WORLD_SHIMS_REFERENCE.md)

---

## 5. Path Decoupling & Portability
AES benchmarks are now fully portable. 
- **Relative Datasets**: `dataset.path` can now be relative to the scenario file (e.g., `./records.csv`), allowing you to share scenario bundles easily.
- **Auto-Industry**: If `industry` is omitted from metadata, the harness will attempt to infer it from the parent directory or tag it as `local`.

---

## 6. Replaying Execution (`run.jsonl`)
Every AES evaluation produces a `run.jsonl` flight recorder log. You can replay this log to debug specific "crashes" or "wrong turns":
```bash
agentv replay --run-id <id>
```

---

## 7. Complete Example (Loan Approval)

Below is a production-grade AES v1.3 scenario demonstrating a multi-stage loan approval process with tool requirements and policy constraints.

```json
{
  "aes_version": 1.4,
  "metadata": {
    "id": "loan-approval-v1",
    "name": "High-Density Loan Credit Audit",
    "industry": "finance",
    "capabilities": ["credit_score_analysis", "policy_lookup"],
    "standards_registry": ["ISO_20022_LOAN_V1"],
    "compliance_level": "Standard",
    "agent_topology": {
      "loan_agent": {
        "reads": ["user.credit_score", "bank.policies"],
        "writes": ["loan.status"]
      }
    }
  },
  "description": "Evaluate an agent's ability to process a loan while adhering to strict internal credit policies.",
  "workflow": {
    "nodes": [
      {
        "id": "task-1",
        "task_description": "Approve the loan for Alice at the standard rate.",
        "required_tools": ["check_credit_score", "approve_loan"],
        "success_criteria": [
          {"metric": "tool_call_correctness", "threshold": 1.0},
          {"metric": "policy_compliance", "threshold": 1.0}
        ]
      },
      {
        "id": "task-2",
        "task_description": "Explain the decision and provide the next steps for disbursement.",
        "success_criteria": [
          {"metric": "path_parsimony", "threshold": 0.5}
        ]
      }
    ],
    "edges": [
      { "from": "task-1", "to": "task-2" }
    ]
  }
}
```
---
 
 ## 8. Behavioral Fingerprinting (V1)
 
### 🛡️ Environmental DNA & Forensic Verification
To ensure that an evaluation trace genuinely reflects the intended scenario logic, AES v1.4 enforces the **Forensic Evidence Ledger**. This provides a verifiable "baseline" for the physical world state (IDs, API keys, and simulator configurations) during the evaluation.
 
 | Field | Description |
 | :--- | :--- |
 | `version` | The Fingerprint schema version (currently `1.0`). |
 | `engine` | The version of the `agentv` engine used. |
 | `timestamp` | UTC ISO-8601 creation time. |
 | `topology_hash` | SHA-256 hash of the `scenario.workflow` structure. |
 | `tool_dna_hash` | Hash of the tool definitions and descriptions available to the agent. |
 | `fingerprint_v1` | A cryptographic digest ensuring the behavioral baseline was not tampered with. |
 
 These fingerprints are used by the `gate` command to verify that a `run.jsonl` trace was generated against a sanctioned version of the scenario and tools.

---
 
 ## 9. Forensic Environmental DNA (v1.4.0) 
 
 v1.4 elevates the environment from a background configuration to a **First-Class Member** of the evaluation trace.
 
 ### The Cumulative Industrial Registry
 Infrastructure state is managed via a **Decoupled Cumulative Registry**. Unlike legacy models, the registry is no longer a single file but a layered configuration stack:
 1. **Immutable Core Root**: Sanctioned defaults are internalized at [eval_runner/resources/shim_resources.json](/eval_runner/resources/shim_resources.json).
 2. **Distributed Extensions**: Extensions safely add or refine logic via the [.aes/config/shims.d/](/.aes/config/shims.d/) directory.
 
 ### 9.1 Capability-Based Routing
 To ensure infrastructure abstraction, AES v1.4+ scenarios should list required capabilities instead of hardcoded endpoints. The Core resolves these to physical infrastructure via the [Routing Manifest](/.aes/config/routing/manifest.json).
 
 This allows a single AES benchmark to be portable across diverse physical environments (local dev, staging, production) by simply layering the appropriate registry overlay.
 
 ### Provisioning Snapshots
 Every `run.jsonl` trace now includes:
 1.  **`environmental_snapshot`**: A point-in-time capture of the final merged registry state.
 2.  **`provisioning_hash`**: A SHA-256 cryptographic link ensuring that the environment used for evaluation has not drifted from the sanctioned baseline.
 
 These features ensure that results are not just "reproducible" but "forensically verifiable" in regulated sectors like Finance and Healthcare.
 
 > [!IMPORTANT]
 > **Trust Protocol Alignment**: While the Open Core provides the *verification* logic for these fingerprints, the *generation* of advanced high-fidelity Behavioral DNA remains a feature of the Enterprise Edition to ensure proprietary industrial logic is protected.
 
 ---
 
 ## 10. Industrial Standards Registry
 
 To support high-stakes AI evaluations, the harness includes a centralized **Standards Registry**. This system allows practitioners to bootstrap evaluation environments that are pre-aligned with recognized global standards.
 
 ### Scaffold Environments
 ```bash
 agentv init --standard ISO_20022
 ```
 
 - **Standards Coverage**: Finance (ISO 20022), Healthcare (HL7 FHIR), Manufacturing (Digital Twins), Logistics (JSON-LD Traceability).
 - **Compliance Mapping**: Scenarios scaffolded via the registry are automatically populated with the necessary `compliance_level` and metadata required for regulatory auditability.
 - **Infrastructure Alignment**: Registry-driven scaffolding ensures all required **World Shims** (databases, APIs, security vaults) are correctly mounted.
 
 ---
 
## 11. Versioning & Provenance (v1.3.0)

To support high-stakes industrial audits, AgentV strictly decouples the **Standard Specification** from the **Execution Engine**:

### `aes_version` (The Standard)
Refers to the **Agent Eval Standard** itself (e.g., `1.3`). It defines the schema and vocabulary of the [scenario.json](/eval_runner/loader.py).
- **v1.2**: Legacy-Stable. Supports basic tasks and simulators.
- **v1.3**: Maintenance. Supports **Forensic DNA** and **PBAC**.
- **v1.4**: Current-Stable. Supports **VC v3**, **Capabilities**, and **Identity Registry**.

### `harness_version` (The Engine)
Refers to the **AgentV Engine** build (e.g., `1.3.0`). This is automatically injected into the [run.jsonl](/eval_runner/verifier.py) and manifest by the "Referee."

> [!IMPORTANT]
> **Industrial Rule**: A single `aes_version` standard can be satisfied by multiple `harness_version` engine builds (bugfixes, optimizations), but a trace is only **Forensically Valid** if the `harness_version` supports the requested `aes_version`.

---

 ## 12. Forensic Trace Logging (`run.jsonl`)
 
 Every evaluation generates a machine-readable `run.jsonl` file. This log is the "Flight Recorder" for the agent's behavior.
 
 ### Event-Stream Architecture
 The log is a stream of JSON objects, each representing an atomic event in the evaluation lifecycle.
 
 #### 🚀 `run_start` (The Forensic DNA)
 The first event in every trace. In **v1.3**, this event is hardened for auditability:
 ```json
 {
   "event": "run_start",
   "timestamp": "2026-04-06T20:00:00Z",
   "payload": {
     "id": "fintech_11198",
     "aes_version": 1.3,
     "environmental_snapshot": {
       "shims": { "database": { "url": "..." }, "api": { ... } },
       "provisioning_hash": "sha256:abcd..."
     }
   }
 }
 ```
 
 #### 🛠️ `tool_call` & `tool_result`
 Captured for every interaction with a **World Shim**.
 - **`tool`**: The registry key of the simulator used.
 - **`action`**: The specific action invoked.
 - **`observation`**: The raw return value from the shim.
 
 #### 🏁 `run_end`
 Contains the final evaluation results, including the NIST-aligned **VerificationResult**.
 
 ---
 
 ## 13. Regulatory Compliance Gating (`gate`)
 The `gate` command validates these traces against the **Trust Protocol**. It ensures that:
 1. The trace has a valid **ED25519 signature**.
 2. The `provisioning_hash` matches the currently sanctioned environment configuration.
 3. The `harness_version` is compatible with the `aes_version` of the scenario.
 
 > [!SUCCESS]
 > **Certification Complete**: A trace that passes the `gate` command is considered a **Certified Industrial Artifact**, ready for regulatory submission.
