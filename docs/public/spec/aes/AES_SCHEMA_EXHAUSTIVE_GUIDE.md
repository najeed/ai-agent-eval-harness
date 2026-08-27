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
| `aes_version` | `number` | **Required** | Specifies schema logic version. Must be `1.4`. |
| `metadata` | `object` | **Required** | Identification, compliance frameworks, topologies, and policies. |
| `workflow` | `object` | **Required** | The execution DAG: tasks, transitions, dependencies, and state hygiene. |
| `evaluation` | `object` | **Required** | Consensus grading panel, IJA threshold, and oracle strategies. |
| `tools` | `object` | *Optional* | Deterministic tool mocks, output schemas, and nested state mutations. |
| `initial_state` | `object` | *Optional* | World Genesis state seeded into the sandbox before turn 1. |
| `environmental_snapshot` | `object` | *Optional* | Sanitized point-in-time snapshot of the infrastructure registry. |
| `enabled_shims` | `array` | *Optional* | Explicit whitelist of world simulators to activate (e.g. `["jira", "sql"]`). |
| `failure_policy` | `string` | *Optional* | DAG execution policy: `fail_fast`, `continue_independent`, `compensate_then_fail`, `best_effort`. |
| `cleanup_workspace` | `boolean` | *Optional* | `true` (default) purges workspace on teardown; `false` preserves disk state for forensics. |
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

| Property | Type | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `id` | String | `fintech-audit-001` | Machine-readable unique identifier for the scenario. |
| `name` | String | "Loan Approval Audit" | Human-readable title used in reports. |
| `compliance_level` | Enum | `Standard`, `Gold`, `Regulatory_Audit` | Sets the strictness of the forensic chain (see below). |
| `standards_registry`| Array | `["GDPR", "PCI_DSS_V4"]` | Maps the test to real-world legal frameworks (GDPR, PCI, HIPAA). |
| `description` | String | "Evaluates loan logic..." | Detailed business context for cataloging. |
| `complexity` | Enum | `low`, `medium`, `high` | Qualitative difficulty assessment. |
| `agent` | Object | `{ "protocol": "http" }` | Explicit agent routing override. |

| `agent_topology` | Object | `{ "underwriter": { "writes": ["db:*"] } }` | Defines agent permissions and resource namespaces. |
| `policies` | Object | `{ "101": { "name": "No PII" } }` | Behavioral constraints and enforcement rules. |
| `provisioning_hash` | String | SHA3-256 | Cryptographic anchor for the infrastructure state. |
| `capabilities` | Array | `["pii_scanner", "gpu"]` | Infrastructure requirements for the runner environment. |


1.  **`id` / `name`**: 
    - **Purpose**: `id` is the machine-link (e.g., `fintech-001`). `name` is the human-friendly title (e.g., "Standard Underwriting Happy Path").
    - **Config**: Strings. IDs should be slug-ified (no spaces).
2.  **`compliance_level`**:
    - **Purpose**: Sets the strictness of the audit. 
    - **Config**: Enum: `Standard`, `Gold`, `Regulatory_Audit`.
3.  **`standards_registry`**:
    - **Purpose**: This is the most powerful part of the metadata. It maps your test to real-world laws.
    - **Config**: An array of strings like `["GDPR", "PCI_DSS_V4", "BASEL_III"]`. By listing these, you trigger specialized forensic checks in the harness. As of v1.4.0, the registry supports **60+ industrial standards**, including ISO 42001, NIST AI-RMF, and HIPAA.
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
    - **Config**: String (auto-populated by the harness during `agentv certify`). This serves as the **Cryptographic Anchor**, mathematically binding the evaluation trace to the exact versions of tools and simulators used during the run.
9.  **`capabilities`**:
    - **Purpose**: Infrastructure requirements.
    - **Config**: Array of strings (e.g., `["gpu", "vpc_access"]`). If the runner doesn't have these, the test won't run. This triggers **Discovery-Override** logic, allowing the harness to dynamically route the scenario to an environment that satisfies these prerequisites.

### Routing Priority: Discovery vs. Pinning
To maintain scalability in industrial clusters, AgentV uses a three-tier routing hierarchy:
1.  **CLI Override** (`--agent http://...`): Highest priority. Explicitly points the harness to a specific endpoint.
2.  **Discovery (Capabilities)**: The industrial standard. If `capabilities` (e.g., `["gpu", "vault"]`) are defined, the harness performs a **Discovery-Override**, even if a manual agent is pinned in the metadata.
3.  **Static Pinning (`metadata.agent`)**: The fallback layer. Used during development to hard-link a scenario to a specific agent without registry resolution.

### Differential Compliance: Use Cases
`compliance_level` takes the following values:

| Level | Focus | Primary Use Case |
| :--- | :--- | :--- |
| **Standard** | Logical Correctness | **Local Dev & Unit Testing**: "Did the agent get the right answer?" (Minimal forensic overhead). |
| **Gold** | Process Integrity | **Staging & Integration**: "Did the agent follow the internal protocol?" (Full tool-logs and trace captures). |
| **Regulatory_Audit** | Non-Repudiation | **Production Certification**: "Can we legally prove the agent was compliant and the evidence is untampered?" (Signed Merkle roots, Vaulting). |

### Proposed Compliance Architecture
When you list `GDPR` in the `standards_registry`, the harness doesn't just "label" the test. It triggers **Capability Mapping**. For example, a `CompliancePlugin` sees `GDPR` and automatically injects the `PII_Scanner` sidecar. This sidecar intercepts all tool outputs and redacts sensitive data before it reaches the forensic log.

Listing `GDPR` in the `standards_registry` is currently a metadata label. We have **proposed** the `CompliancePlugin` extension to transform these into active triggers:
- **Automatic Injection**: Detection of `GDPR` would automatically inject the `pii_scanner` capability from the routing manifest.
- **In-Flight Redaction**: A compliance-aware sidecar would intercept tool outputs and redact sensitive data (PII) before it is committed to the forensic ledger.

### Governance Resolution Protocol
When conflicts arise between high-level frameworks (`standards_registry`) and explicit scenario `policies`, AgentV applies the **Maximum Restriction Matrix** to determine the safe path:

1.  **Specific Over General**: Local `policies` always take precedence over general framework defaults.
2.  **The Restrictiveness Calculation**:
    - **Scalar Minimization**: The lowest numeric value wins (e.g., a 30s timeout override takes precedence over a 60s framework default).
    - **Boolean Intersection**: Enabled constraints (`true`) take precedence over disabled ones.
    - **Namespace Shrinkage**: The most specific resource scope wins (e.g., `writes: ["db:audit_log"]` over `writes: ["db:*"]`).

> [!IMPORTANT]
> If a conflict is logically irreconcilable (e.g., Framework requires data vaulting while Policy requires raw cloud export), the harness will trigger a **Governance Fault** and mark the run as **Inconclusive**.

### 🏗️ Walkthrough Part 1: Initial Setup
We are building a **Fintech Underwriting persistence Audit**. We start with the Metadata.

```json
{
  "aes_version": 1.4,
  "metadata": {
    "id": "fintech_persistence_010",
    "name": "Underwriter Recovery & Persistence Test",
    "compliance_level": "Regulatory_Audit",
    "standards_registry": ["PCI_DSS_V4", "SOC2_T2"],
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

The `tools` manifest defines deterministic mock responses, execution outputs, and atomic state mutations executed within the `ToolSandbox`.

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
This guarantees exact alignment with `PathResolver.resolve(state, "risk.assessment.rating")`, `state_hygiene` pre-checks, and `StateParityVerifier`.

---

## Lesson 3: The DAG Engine (The Workflow Block)

The `workflow` block maps the execution graph using a Directed Acyclic Graph (DAG) of Nodes and Edges.

### Workflow Failure Policies (`failure_policy`)

The `failure_policy` root field dictates how the `WorkflowInterpreter` handles errors and timeouts:

| Failure Policy | Execution Behavior |
| :--- | :--- |
| **`fail_fast`** *(Default)* | Terminates the workflow immediately upon the first unhandled node failure or timeout. |
| **`continue_independent`** | Independent parallel branches proceed to completion even if a sibling branch fails. |
| **`compensate_then_fail`** | Executes rollback/compensation edges (Saga pattern) before failing the workflow. |
| **`best_effort`** | Attempts all reachable nodes regardless of upstream errors to maximize metric collection. |

### Property Table

| Property | Type | Context | Purpose |
| :--- | :--- | :--- | :--- |
| `nodes` | Array | Root | The sequence of tasks the agent must perform. |
| `node.id` | String | Node | Unique identifier for the step (e.g., `verify_id`). |
| `node.task_description` | String | Node | The prompt sent to the agent for this specific step. |
| `node.required_tools` | Array | Node | The allowed tools (shims) for this step. |
| `node.success_criteria` | Array | Node | Quantitative metrics for task success. |
| `node.state_hygiene` | Object | Node | Pre-condition assertions on the environment state before execution. |
| `node.expected_outcome` | Object | Node | Ground truth used to grade the agent's response. |
| `edges` | Array | Root | Conditional transitions between nodes (success/failure/error/timeout). |

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
      "expected_outcome": {
        "type": "typed_value",
        "data_type": "string",
        "value": "VALID"
      }
    },
    {
      "id": "persist_decision",
      "task_description": "Write the 'APPROVED' status to the primary ledger log.",
      "required_tools": ["ledger_write"],
      "expected_outcome": {
        "type": "typed_value",
        "data_type": "boolean",
        "value": true
      }
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
| Property | Type | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `strategy` | Enum | `Majority_Vote` | How to resolve disagreements (`Majority_Vote`, `Weighted_Average`, `Absolute_Unanimity`). |
| `min_judges` | Integer | 1 | Minimum number of LLM judges required for a valid certification. |
| `judge_panel` | Array | `["default"]` | List of models (e.g., `["gpt-5.6", "claude-opus-5", "gemini-3.7-flash"]`). |
| `ija_threshold` | Float | 0.8 | Minimum agreement ratio (0.0 to 1.0) before flagging run as "Inconclusive". |

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
* **`true` (Default)**: During `sandbox.teardown()`, the engine deletes all ephemeral filesystem assets, mock databases, and temporary directories to prevent disk leakage.
* **`false` (Debug / Forensics)**: Preserves the sandbox directory intact on disk under `workspace/` so engineers can inspect output artifacts and state side-effects.

### Forensic Vaulting
1. **T_end**: Execution completes.
2. **Snapshot**: `ForensicCollector` captures a point-in-time image of execution traces, logs, and database states.
3. **Vaulting**: Moved to immutable `runs/<run_id>/forensics/` store.
4. **Certification**: Verification Certificate (VC) issued with ED25519 signature and Merkle commitment.

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
        "expected_outcome": {
          "type": "typed_value",
          "data_type": "string",
          "value": "APPROVED"
        }
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


