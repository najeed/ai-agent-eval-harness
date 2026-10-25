# AES Schema Masterclass: Industrial Standards & Plumbing (v1.4.0)
**Specification Version:** 1.4.0

Welcome to the definitive guide to the **Agent Evaluation Specification (AES)**. This document is designed to take you from a novice understanding to a master-level grasp of how we define, configure, and audit agentic intelligence using the AgentV harness. It ties abstract schema fields to the physical **Plumbing** in the `.aes/` configuration and cryptographic identity store and outlines the **Governance Architecture** for industrial-grade compliance.

---

## The Foundation: What is AES?

Think of an **AES file** as the **DNA of an evaluation scenario**. 
If you were testing an autonomous agent or human pilot, you wouldn't just say "Fly the plane." You would provide a flight plan (Workflow DAG), a manifest of authorized tools (Tool Sandbox), a set of behavioral rules and guardrails (Policies), an initial world state (Genesis State), and an objective scorecard (Multi-Judge Consensus Panel).

The AES schema is a strictly typed JSON or YAML contract that instructs the AgentV harness how to execute, isolate, observe, and mathematically certify an AI agent's execution.

---

## The Spine: Root Properties

Every AES v1.4 scenario adheres to a strict schema with `"additionalProperties": false` enforced at the root. Misplaced properties (such as putting `policies` or `agent_topology` at the top level instead of inside `metadata`) will immediately fail schema validation.

| Attribute | Type | Requirement | Purpose |
| :--- | :--- | :--- | :--- |
| `$schema` | `string` | Optional | Optional JSON Schema identifier. |
| `aes_version` | `number` | **Required** | Specifies schema logic version. Must be exactly `1.4`. |
| `metadata` | `object` | **Required** | Identification, compliance frameworks, topologies, and policies. |
| `workflow` | `object` | **Required** | The execution DAG: tasks, transitions, dependencies, and state hygiene. |
| `evaluation` | `object` | **Required** | Consensus grading panel, IJA threshold, and oracle strategies. |
| `tools` | `object` | *Optional* | Deterministic tool mocks, output schemas, and nested state mutations. |
| `initial_state` | `object` | *Optional* | World Genesis state seeded into the sandbox before turn 1. |
| `environmental_snapshot` | `object` | *Optional* | Scenario-supplied environment snapshot. |
| `enabled_shims` | `array` | *Optional* | Explicit whitelist of world simulators to activate (e.g. `["jira", "sql"]`). |
| `failure_policy` | `string` | *Optional* | DAG execution policy: `fail_fast`, `continue_independent`, `compensate_then_fail`, `best_effort`. |
| `cleanup_workspace` | `boolean` | *Optional* | Requests workspace cleanup. The AES schema defines no default. |
| `description` | `string` | *Optional* | High-level scenario synopsis for catalogs and reporting. |
| `industry` | `string` | *Optional* | Target vertical (e.g. `Healthcare`, `Fintech`, `Telecom`). |
| `use_case` | `string` | *Optional* | Specific domain problem (e.g. `KYC Verification`, `SIM Swap Fraud`). |

---

## 🏗️ Storage Boundaries & Registry Plumbing

Understanding the separation between persistent configuration, cryptographic identity, and transient execution workspaces is essential:

| Directory Store | Scope | Purpose |
| :--- | :--- | :--- |
| **`.aes/`** | **Persistent / Key Store** | Stores cryptographic keys, signing certs, root trust anchors, and master config. |
| **`/tmp`, `/scratch_tmp`** | **Transient Scratch** | Ephemeral file downloads, AST analyzer tarball caches, and throwaway scratchpads. |
| **`/workspace` (Jail)** | **Sandbox Jail** | Isolated execution environment generated per run with virtual filesystem boundaries (`vfs:/`). |
| **`runs/<run_id>/`** | **Forensics Vault** | Immutable execution logs, Merkle trees, and signed Verification Certificates. |


---

## Lesson 1: Infrastructure DNA (The Metadata Block)

### Property Table

| Property | Type | Requirement | Purpose |
| :--- | :--- | :--- | :--- |
| `id` | string | **Required** | Machine-readable scenario identifier. |
| `name` | string | **Required** | Human-readable scenario name. |
| `compliance_level` | enum | **Required** | `Standard`, `Gold`, or `Regulatory_Audit`. |
| `standards_registry`| array | Optional | Registered standards identifiers. |
| `description` | string | Optional | Metadata description. |
| `complexity` | enum | Optional | `low`, `medium`, or `high`. |
| `agent` | object | Optional | May contain string `protocol` and string `endpoint`. |

| `agent_topology` | object | Optional | Agent map; each agent may define string arrays `reads` and `writes`. |
| `policies` | object | Optional | Policy object; its members are unconstrained by this schema. |
| `provisioning_hash` | string | Optional | SHA3-256 hash of resolved shim resources. |
| `capabilities` | array of strings | Optional | Required routing capabilities. |


1.  **`id` / `name`**: 
    - **Purpose**: `id` is the machine-link (e.g., `fintech-001`). `name` is the human-friendly title (e.g., "Standard Underwriting Happy Path").
    - **Config**: Strings. IDs should be slug-ified (no spaces).
2.  **`compliance_level`**:
    - **Purpose**: Sets the strictness of the audit. 
    - **Config**: Enum: `Standard`, `Gold`, `Regulatory_Audit`.
3.  **`standards_registry`**:
    - **Purpose**: This is the most powerful part of the metadata. It maps your test to real-world laws.
    - **Config**: An array of registered identifiers such as `["GDPR", "PCI_DSS_V4", "BASEL_III"]`. The schema allows 64 identifiers; the complete list appears in the schema reference below.
4.  **`agent_topology`**:
    - **Purpose**: Defines what the agent is *allowed* to touch.
    - **Config**: A map of agent names to their `reads` and `writes` (e.g., `agent_1: { "writes": ["ledger_db"] }`). This implements **Permissions-Based Access Control (PBAC)**, ensuring that agents are isolated within their specific resource namespaces.
5.  **`description` / `complexity`**:
    - **Purpose**: Industrial metadata for scenario catalogs. Enables quick filtering of "High Complexity Fintech" runs.
    - **Config**: Strings and Enums.
6.  **`agent`**:
    - **Purpose**: `agent` allows a local override of the global routing.
    - **Config**: Object.
7.  **`policies`**:
    - **Purpose**: The "Active Ingredients" of compliance. Defines the ruleset audited by the `CompliancePlugin`.
    - **Config**: A dictionary of objects (e.g., `{"leakage_prevention": {"id": "RULE_101"}}`).
8.  **`provisioning_hash`**:
    - **Purpose**: A SHA3-256 fingerprint of the **Shim Resources**. It ensures the audit trail is tied to a specific infrastructure state.
    - **Config**: String. The schema identifies it as the SHA3-256 hash of the resolved shim resources used for the run.
9.  **`capabilities`**:
    - **Purpose**: Infrastructure requirements.
    - **Config**: Array of strings (e.g., `["gpu", "vpc_access"]`). If the runner doesn't have these, the test won't run. This triggers **Discovery-Override** logic, allowing the harness to dynamically route the scenario to an environment that satisfies these prerequisites.

### Routing Priority: Discovery vs. Pinning
This is runtime guidance, not a JSON Schema rule. The schema only constrains the shape of `metadata.agent` and `metadata.capabilities`.

To maintain scalability in industrial clusters, AgentV uses a three-tier routing hierarchy:
1.  **CLI Override** (`--agent http://...`): Highest priority. Explicitly points the harness to a specific endpoint.
2.  **Discovery (Capabilities)**: The industrial standard. If `capabilities` (e.g., `["gpu", "vault"]`) are defined, the harness performs a **Discovery-Override**, even if a manual agent is pinned in the metadata.
3.  **Static Pinning (`metadata.agent`)**: The fallback layer. Used during development to hard-link a scenario to a specific agent without registry resolution.

### Differential Compliance: Use Cases
The following descriptions are product guidance. The schema itself constrains `compliance_level` only to the three values shown.

`compliance_level` takes the following values:

| Level | Focus | Primary Use Case |
| :--- | :--- | :--- |
| **Standard** | Logical Correctness | **Local Dev & Unit Testing**: "Did the agent get the right answer?" (Minimal forensic overhead). |
| **Gold** | Process Integrity | **Staging & Integration**: "Did the agent follow the internal protocol?" (Full tool-logs and trace captures). |
| **Regulatory_Audit** | Non-Repudiation | **Production Certification**: "Can we legally prove the agent was compliant and the evidence is untampered?" (Signed Merkle roots, Vaulting). |

### Standards Registry Is Declarative
`standards_registry` is an enum-constrained metadata field. The JSON Schema does not prescribe automatic capability injection, redaction, routing, or compliance-plugin behavior. Treat those as separately versioned runtime policies, not as AES-schema guarantees.

### What the Schema Does and Does Not Govern
The schema validates field structure and listed enum values. It does not define policy-precedence rules, a compliance conflict algorithm, or a run verdict for conflicting policies. Those decisions belong to the active policy evaluator and must not be inferred from an AES document alone.

### 🏗️ Walkthrough Part 1: Initial Setup
We are building a **Fintech Underwriting persistence Audit**. We start with the Metadata.

```json
{
  "aes_version": 1.4,
  "metadata": {
    "id": "fintech_persistence_010",
    "name": "Underwriter Recovery & Persistence Test",
    "compliance_level": "Regulatory_Audit",
    "standards_registry": ["PCI_DSS_V4", "SOC_2"],
    "agent_topology": {
      "loan_agent": {
        "reads": ["ledger_db:*", "kyc_vault:*"],
        "writes": ["ledger_db:audit_log"]
      }
    },
    "policies": {
      "non_disclosure": { "scope": "global", "rules": ["no_pii_logging"] }
    },
    "capabilities": ["secure_sandbox", "audit_trail_validator"]
  }
}
```
> **Note on `ledger_db`**: This represents a **Namespace** in the SharedStateRegistry. It is mapped to a simulator (e.g., a SQL shim) that the agent interacts with.
> **Note on `capabilities`**: These are the "Hardware/Software Prerequisites". If your laptop doesn't have a `secure_sandbox`, the harness will refuse to run this scenario.

---

---

## Lesson 2: Deterministic Tools & Multi-Level State Mutations (The Tools Block)

The root `tools` field is an optional object. AES v1.4 deliberately leaves its inner structure unconstrained so tool providers can publish their own contracts. The example below illustrates one commonly used tool shape; it is not independently enforced by `aes.schema.json`.

### Multi-Level Dotted State Mutation
The runtime uses recursive path resolution (`_set_state_path`) to support deep hierarchical state mutations. Dotted path segments (e.g. `"risk.assessment.rating"`) mutate nested dictionaries rather than creating flat keys:

```json
"tools": {
  "evaluate_risk_profile": {
    "output": {
      "status": "success",
      "risk_tier": "Low"
    },
    "state_changes": [
      {
        "path": "risk.assessment.rating",
        "value": "approved"
      },
      {
        "path": "ledger.accounts.balance",
        "value": 150000.0
      }
    ]
  }
}
```

When this tool executes, `sandbox.state` is mutated to:
```json
{
  "risk": {
    "assessment": {
      "rating": "approved"
    }
  },
  "ledger": {
    "accounts": {
      "balance": 150000.0
    }
  }
}
```
Use the tool contract selected by the active runtime when authoring tool payloads. The AES schema validates only that `tools` is an object.

---

## Lesson 3: The DAG Engine (The Workflow Block)

The `workflow` block maps the execution graph using a Directed Acyclic Graph (DAG) of Nodes and Edges.

### Workflow Failure Policies (`failure_policy`)

The `failure_policy` root field dictates how the `WorkflowInterpreter` handles errors and timeouts:

| Failure Policy | Execution Behavior |
| :--- | :--- |
| **`fail_fast`** | Terminates the workflow immediately upon the first unhandled node failure or timeout. |
| **`continue_independent`** | Independent parallel branches proceed to completion even if a sibling branch fails. |
| **`compensate_then_fail`** | Executes rollback/compensation edges (Saga pattern) before failing the workflow. |
| **`best_effort`** | Attempts all reachable nodes regardless of upstream errors to maximize metric collection. |

### Property Table

| Property | Type | Context | Purpose |
| :--- | :--- | :--- | :--- |
| `nodes` | array | Workflow | **Required.** Each node requires `id` and `task_description`. |
| `node.id` | string | Node | **Required.** Unique identifier for the step. |
| `node.task_description` | string | Node | **Required.** Task instruction. |
| `node.required_tools` | array of strings | Node | Optional required shim tools. |
| `node.success_criteria` | array | Node | Optional; each item requires string `metric` and numeric `threshold`. |
| `node.state_hygiene` | object | Node | Optional object; members are unconstrained by this schema. |
| `node.expected_outcome` | array | Node | Optional assertions; each item requires `target` and `expected`. |
| `edges` | array | Workflow | **Required.** Each edge requires `from` and `to`; `condition` is optional. |

### 🏗️ Walkthrough Part 2: Defining the Graph

```json
"workflow": {
  "nodes": [
    {
      "id": "verify_kyc",
      "task_description": "Verify the Identity for User ID: 9988. Respond with 'VALID' if check passes.",
      "required_tools": ["kyc_verify_api"],
      "state_hygiene": {
        "rules": [
          { "path": "kyc_vault.status", "expected": "online", "op": "eq" }
        ]
      },
      "expected_outcome": [
        {"target": "message", "expected": "VALID", "mode": "exact"}
      ]
    },
    {
      "id": "persist_decision",
      "task_description": "Write the 'APPROVED' status to the primary ledger log.",
      "required_tools": ["ledger_write"],
      "expected_outcome": [
        {"target": "shim:ledger", "property": "approved", "expected": true}
      ]
    }
  ],
  "edges": [
    { "from": "verify_kyc", "to": "persist_decision", "condition": "success" }
  ]
}
```

---

## Lesson 4: The Industrial Jury (The Evaluation Block)

This block configures multi-judge consensus grading, ensuring high-assurance evaluation without single-model bias.

### Property Table
| Property | Type | Schema requirement | Purpose |
| :--- | :--- | :--- | :--- |
| `consensus.strategy` | enum | Required when `consensus` is present | `Majority_Vote`, `Weighted_Average`, or `Absolute_Unanimity`. |
| `consensus.min_judges` | integer | Required when `consensus` is present; minimum `1` | Number of judges required by the consensus configuration. |
| `consensus.judge_panel` | array of strings | Optional | Judge identifiers. |
| `ija_threshold` | number | Optional; inclusive range `0` through `1` | Inter-judge agreement threshold. |

### 🏗️ Walkthrough Part 3: Setting the Jury

```json
"evaluation": {
  "consensus": {
    "strategy": "Majority_Vote",
    "min_judges": 3,
    "judge_panel": ["gpt-5.6", "claude-opus-5", "gemini-3.7-flash"]
  },
  "ija_threshold": 0.9
}
```

---

## Lesson 5: Verification Reconciliation & Lifecycle (Forensics)

### Lifecycle Control: `cleanup_workspace`
* **`true`**: Requests workspace cleanup.
* **`false`**: Requests that cleanup not be enabled by this AES field.

The AES schema defines no default and does not prescribe the runtime cleanup implementation. Runtime configuration may supply additional behavior.

#### Current runtime behavior

`ToolSandbox.teardown()` implements this field as a workspace-directory cleanup switch:

1. It checks `metadata.cleanup_workspace` first. If that key is absent, it checks the schema-defined root `cleanup_workspace` field.
2. If neither field is present, the effective value is `false`, so the run workspace is preserved.
3. If the effective value is `true`, it recursively removes only `workspace/<run_id>/` through `rmtree_resilient()`.

This switch does not control all teardown. Registered resources and cached simulators are cleaned up regardless. The terminal jail is separate: `metadata.cleanup_terminal_jail` controls it when present; otherwise `CLEANUP_TERMINAL_JAIL` defaults to `true`.

### Forensic Vaulting
1. **T_end**: Execution completes.
2. **Snapshot**: `ForensicCollector` captures a point-in-time image of execution traces, logs, and database states.
3. **Vaulting**: Moved to immutable `runs/<run_id>/forensics/` store.
4. **Certification**: Verification Certificate (VC) issued with ED25519 signature and Merkle commitment.

---

## Schema Reference: Registered Standards

The following is the complete enum accepted by `metadata.standards_registry` in `definitions/metadata.json`:

```text
3GPP_5G, BASEL_III, CCPA, CIS_BENCHMARKS, COBIT, COSO_ERM, DCAT, DICOM,
DUBLIN_CORE, ESG_GRI, ESG_ISSB, ESG_SASB, EU_AI_ACT, FEDRAMP, FIPS_140_3,
FISMA, GDPR, GLBA, HIPAA, HITECH, HL7_FHIR_V4, ICD_10, ICD_11, IEC_61850,
IEC_62351, IEC_62443, IEEE_1547, IETF_RFC, ISA_95, ISO_11179, ISO_14001,
ISO_19790, ISO_20022, ISO_23894, ISO_27001, ISO_27701, ISO_31000, ISO_42001,
ISO_45001, ISO_50001, ISO_9001, ISO_9594, LGPD, MIFID_II, NERC_CIP,
NIST_AI_RMF, NIST_CSF, OAUTH_2, OECD_AI_PRINCIPLES, OIDC, OPC_UA,
PCI_DSS_V4, PIPEDA, PSD2, SAML_V2, SOC_2, SOX, SWIFT_MT103,
UNESCO_AI_ETHICS, W3C_OWL, W3C_RDF, W3C_XML, X_509, std-1
```

---

## Full Reference Implementation

A complete, production-grade AES v1.4 scenario:

```json
{
  "$schema": "https://agentv.ai/spec/aes/aes.schema.json",
  "aes_version": 1.4,
  "description": "Production-grade automated commercial loan assessment scenario.",
  "industry": "Fintech",
  "use_case": "Commercial Lending",
  "failure_policy": "fail_fast",
  "cleanup_workspace": true,
  "metadata": {
    "id": "fintech-loan-underwriting-01",
    "name": "Commercial Loan Underwriting Audit",
    "compliance_level": "Regulatory_Audit",
    "standards_registry": ["BASEL_III", "SOX", "PCI_DSS_V4"],
    "agent_topology": {
      "underwriter": {
        "reads": ["kyc:*", "credit_bureau:*"],
        "writes": ["loan_ledger:audit_log"]
      }
    },
    "policies": {
      "disbursement_limit": {
        "id": "max_disbursement",
        "max_limit": 250000.0,
        "constrained_params": ["disbursement_amount"]
      }
    },
    "capabilities": ["secure_vault", "audit_trail_validator"]
  },
  "initial_state": {
    "system_status": "operational",
    "risk": {
      "assessment": {
        "rating": "unassigned"
      }
    }
  },
  "tools": {
    "evaluate_risk_profile": {
      "output": {
        "status": "success",
        "risk_tier": "Low"
      },
      "state_changes": [
        {
          "path": "risk.assessment.rating",
          "value": "approved"
        }
      ]
    }
  },
  "workflow": {
    "nodes": [
      {
        "id": "task_risk_assessment",
        "task_description": "Analyze applicant financial statements and execute evaluate_risk_profile.",
        "required_tools": ["evaluate_risk_profile"],
        "state_hygiene": {
          "rules": [
            { "path": "risk.assessment.rating", "expected": "unassigned", "op": "eq" }
          ]
        },
        "success_criteria": [
          { "metric": "tool_execution_accuracy", "threshold": 1.0 }
        ],
        "expected_outcome": [
          {"target": "message", "expected": "APPROVED", "mode": "exact"},
          {
            "target": "shim:loan_ledger",
            "property": "decision",
            "expected": "APPROVED",
            "mode": "exact"
          }
        ]
      }
    ],
    "edges": []
  },
  "evaluation": {
    "consensus": {
      "strategy": "Majority_Vote",
      "min_judges": 3,
      "judge_panel": ["gpt-5.6", "claude-opus-5", "gemini-3.7-flash"]
    },
    "ija_threshold": 0.90
  }
}
```

> [!TIP]
> **Pro-Tip**: Always run `agentv aes validate <scenario.json>` or use the AgentV VS Code extension before launching evaluation runs to benefit from real-time schema validation and intellisense.


