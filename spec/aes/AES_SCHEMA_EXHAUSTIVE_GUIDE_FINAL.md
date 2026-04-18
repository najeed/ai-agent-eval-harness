# AES Schema Masterclass: Industrial Standards & Plumbing (v1.4.0)
**Specification Version:** 1.4.0

Welcome to the definitive guide to the **Agent Evaluation Specification (AES)**. This document is designed to take you from a novice understanding to a master-level grasp of how we define, configure, and audit agentic intelligence using the AgentV harness. It ties abstract schema fields to the physical **Plumbing** in the `.aes/` registry and outlines the **Proposed Governance Architecture** for industrial-grade compliance.

---

## The Foundation: What is AES?

Think of an **AES file** as the **DNA of a test**. 
If you were testing a human pilot, you wouldn't just say "Fly the plane." You would give them a flight plan, a list of authorized tools (radio, GPS), a set of safety rules (don't fly over the city), and a scorecard (did you land on the center line?). 

The AES schema is exactly that—a structured JSON or YAML file that tells the AgentV harness how to "train the camera" on an AI agent to see if it's safe, smart, and compliant.

---

## The Spine: Root Properties
Every AES file starts with five high-level sections. 

| Attribute | Type | Purpose | How to Configure |
| :--- | :--- | :--- | :--- |
| `aes_version` | `number` | **Crucial.** Tells the engine which logic set to use. | Must be `1.4` for current industrial features. |
| `metadata` | `object` | The "Header" info. Identity and Rules. | See Lesson 1. |
| `workflow` | `object` | The "Map". Tasks and Transitions. | See Lesson 2. |
| `evaluation` | `object` | The "Judge". How we measure success. | See Lesson 3. |
| `initial_state` | `object` | **World Genesis**. Seeds the World State before node 1. | Mapped to `SharedStateRegistry`. |
| `environmental_snapshot` | `object` | **Freeze Frame**. A resolved snapshot of the infrastructure registry captured at run start. | Injected by the engine. |

---

## 🏗️ The Registry Bridge: Plumbing vs. Spec

The AES JSON file is a **Blueprint**, but the actual **Resources** live in the project registry.

| Spec Field | Registry Location (in `.aes/config/`) | Purpose |
| :--- | :--- | :--- |
| `capabilities` | `routing/manifest.json` | Infrastructure requirements (e.g., Secure Vault). |
| `required_tools` | `shims.d/*.json` | Functional tool definitions (e.g., `loan_ledger_shim`). |
| `judge_panel` | `routing.d/judges.json` | LLM endpoints and provider configurations. |
| `agent_topology` | `plugins/registry.json` | Role-based access control for multiple agents. |

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
| `forensics` | Array | `["FINTECH_DNA_V1"]` | Tags for automated artifact collation. |
| `agent_topology` | Object | `{ "underwriter": { "writes": ["db:*"] } }` | Defines agent permissions and resource namespaces. |
| `policies` | Object | `{ "101": { "name": "No PII" } }` | Behavioral constraints and enforcement rules. |
| `provisioning_hash` | String | SHA-256 | Cryptographic anchor for the infrastructure state. |
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
    - **Config**: A map of agent names to their `reads` and `writes` (e.g., `agent_1: { "writes": ["ledger_db"] }`). This implements **Permissions-Based Access Control (PBAC)**, ensuring that agents are isolated within leurs specific resource namespaces.
5.  **`description` / `complexity`**:
    - **Purpose**: Industrial metadata for scenario catalogs. Enables quick filtering of "High Complexity Fintech" runs.
    - **Config**: Strings and Enums.
6.  **`agent` / `forensics`**:
    - **Purpose**: `agent` allows a local override of the global routing. `forensics` provides anchor tags for result aggregators (e.g., "Find all runs with FINTECH_DNA").
    - **Config**: Objects and Arrays.
7.  **`policies`**:
    - **Purpose**: The "Active Ingredients" of compliance. Defines the ruleset audited by the `CompliancePlugin`.
    - **Config**: A dictionary of objects (e.g., `{"leakage_prevention": {"id": "RULE_101"}}`).
8.  **`provisioning_hash`**:
    - **Purpose**: A SHA-256 fingerprint of the **Shim Resources**. It ensures the audit trail is tied to a specific infrastructure state.
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

## Lesson 2: The DAG Engine (The Workflow Block)
The `workflow` is a **DAG** (Directed Acyclic Graph). It’s a map of steps (Nodes) and the paths between them (Edges). The Workflow defines the "Flight Plan" using a Directed Acyclic Graph (DAG) of Nodes and Edges.

### Property Table

| Property | Type | Context | Purpose |
| :--- | :--- | :--- | :--- |
| `nodes` | Array | Root | The sequence of tasks the agent must perform. |
| `node.id` | String | Node | Unique identifier for the step (e.g., `verify_id`). |
| `node.task_description` | String | Node | The prompt sent to the agent for this specific step. |
| `node.required_tools` | Array | Node | The allowed tools (shims) for this step (defined in `shim_resources.json`). |
| `node.success_criteria` | Array | Node | Quantitative metrics for task success (v1.4 upgrade). |
| `node.state_hygiene` | Object | Node | Pre-condition checks (assertions) on the environment state. |
| `node.expected_outcome` | Object | Node | The "Ground Truth" used to grade the agent's response. |
| `edges` | Array | Root | Conditional transitions between nodes (success/failure/error). |


1.  **`task_description`**:
    - **Purpose**: The actual prompt or instruction sent to the agent.
    - **Config**: Clear, descriptive natural language.
2.  **`required_tools`**:
    - **Purpose**: The "Keys" to the room. The agent can *only* use tools listed here for this task.
    - **Config**: Array of tool IDs defined in your `shim_resources.json`. This enables **Task-Level Isolation**, ensuring an agent cannot use sensitive tools (e.g., `bank_write`) in a read-only node.
3.  **`success_criteria`**:
    - **Purpose**: Quantitative thresholds for this step (e.g., "Latentcy < 200ms").
    - **Config**: Array of objects with `metric` and `threshold`. This allows the engine to perform automated, multi-dimensional grading of task-specific performance.
4.  **`state_hygiene`**:
    - **Purpose**: A "Pre-flight Check." It ensures the environment hasn't been tampered with *before* the agent starts.
    - **Config**: Object containing assertions (e.g., `database_locked: true`). This implements **Assertions-First Logic**, preventing evaluations from proceeding in a corrupted environment.
4.  **`expected_outcome`**:
    - **Purpose**: The "Ground Truth." What should the world look like if the agent wins?
    - **Config**: Can be a `typed_value` (e.g., a specific string) or a `standard_ref` (linking to a shared schema).

### Deep-Dive: State Hygiene & Tools
- **State Hygiene**: How does the engine know `database_locked`? It checks the internal state of the `ToolSandbox`. If the `loan_ledger` simulator reports its status as "locked", the assertion pass. This is **not** a hardcoded set of keys. It is a **Contract** defined in the `.aes/config/shims.d/` registry for a specific simulator:
1.  **Definition**: The `loan_ledger_shim` (a simulator) defines its state output schema.
2.  **Mapping**: In your workflow, you list `database_locked: true`.
3.  **Real-Time Verification**: The harness queries the `SharedStateRegistry` (grounded in the active shim). If the shim reports its current state as locked, the assertion passes.
4.  **Configuration**: You define which sims are active and their initial state in the **Shim Registry**.
> **The Limited Set**: The assertions you can use are determined by the **Simulator Schema** of the shims you enable.

- **Tools vs. Capabilities**: 
    - `Capabilities` = The environment (e.g., "Do we have a vault?").
    - `Tools` = The key (e.g., `vault_read`). An agent might be in a "Vault Environment" (Capability) but not have the "Vault Key" (Tool) for a specific task.

### 🏗️ Walkthrough Part 2: Defining the Graph
The agent must verify a KYC record and then persist the decision to the ledger.

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

## Lesson 3: The Industrial Jury (The Evaluation Block)

This block tells the harness how to calculate the final grade. Without this, the engine can only record the trace; it cannot "Certify" it.

### Property Table
| Property | Type | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `strategy` | Enum | `Majority_Vote` | How to resolve disagreements between judges. |
| `min_judges` | Integer | 1 | minimum number of LLM judges required for a valid certification. |
| `judge_panel` | Array | `["default"]` | List of specific models (e.g., `gpt-4o`, `claude-3.5-sonnet`). |
| `ija_threshold` | Float | 0.8 | minimum agreement (0.0 to 1.0) before the result is flagged as "Inconclusive". |


1.  **`consensus`**:
    - **Purpose**: For complex tasks, we don't trust just one "Judge" (LLM). We use a panel.
    - **Config**: 
        - `strategy`: `Majority_Vote` or `Weighted_Average`.
        - `min_judges`: How many judges must agree.
2.  **`ija_threshold` (Inter-Judge Agreement)**:
    - **Purpose**: How much disagreement do we tolerate before we flag the result as "Inconclusive"?
    - **Config**: Float between `0.0` and `1.0`. `0.9` means the judges must be highly aligned.

### Deep-Dive: Consensus Strategies
- **Majority_Vote**: The most frequent score wins (e.g., [1.0, 1.0, 0.5] -> 1.0). Used for discrete reasoning tasks.
- **Weighted_Average**: Scores are averaged, potentially with different weights per model. Used for consistency testing.
- **Absolute_Unanimity**: Every judge must return the exact same score. If a single judge diverges, the run is flagged as Inconclusive. Used for high-risk financial or clinical decisions.
- **The Inconclusive State**: If your judges disagree (agreement < `ija_threshold`), the Trust Protocol marks the run as **"Inconclusive - Human Review Required"**. This prevents "Hallucinated Certifications."

### Consensus Math & Normalization
How does `Majority_Vote` work?
- **Discrete Levels (Exact)**: If scores are [1.0, 1.0, 0.5], **1.0 Wins**.
- **Normalization (Fuzzy)**: If judges return fuzzy scores (e.g., [0.98, 0.99, 0.8]), the engine applies a **Confidence Bucket**. 
    - Standard normalization might bin these into "Pass" (>= 0.9) and "Fail".
    - If agreement < `ija_threshold` (e.g., 0.95), the run is flagged as **Inconclusive**.
- **The Inconclusive Trigger**: If the distance between judges is too great (Agreement < `ija_threshold`), the harness refuses to certify the result and flags it for Human Review.

### Judge Configuration
Models like `gpt-4o` in the `judge_panel` are resolved via the **Routing Registry** (`.aes/config/routing/manifest.json`). This protects your scenario from breaking if you swap providers (e.g., moving from OpenAI to an internal Ollama cluster).

### 🏗️ Walkthrough Part 3: Setting the Jury
We use a panel of three judges to ensure the underwriting decision isn't a fluke.

```json
"evaluation": {
  "consensus": {
    "strategy": "Majority_Vote",
    "min_judges": 3,
    "judge_panel": ["gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]
  },
  "ija_threshold": 0.9
}
```

---

## Lesson 4: Verification Reconciliation (Forensics)
These are attributes you **don't** write in the spec, but the harness **injects** into the audit trail.

### Property Table
| Property | Source | Purpose |
| :--- | :--- | :--- |
| `provisioning_hash` | Registry | A SHA-256 fingerprint of the **Environment DNA** (all shim versions and configs). |
| `environmental_snapshot` | Config | A sanitized "Freeze Frame" of the infrastructure state at T=0. |
| `trace_signature` | Identity | An ED25519 signature of the entire run manifest. |

1.  **`provisioning_hash`**:
    - **Purpose**: A digital fingerprint of the environment. If one file in your database is different, the hash changes, and the audit fails.
2.  **`environmental_snapshot`**:
    - **Purpose**: A literal "Freeze Frame" of the server, tools, and data at the exact second the test started.
    - **Details**: Unlike the static `provisioning_hash`, this is a sanitized, point-in-time capture of the resolved `shim_resources.json`. It provides auditors with the high-fidelity context needed to reconstruct the exact world state during a forensic review.

### Technical Reconciliation
- **The Persistence Problem**: "If the database changes during the test, how does the hash pass?"
- **The Answer**: The `provisioning_hash` does **not** track your changing data; it tracks the **Tool Configuration**. It ensures that if a verification request is issued, the verifier uses the *exact same* tool versions that were used at "Flight Time." The changing data is tracked via the **Forensic Ledger** which hashes every disk change during the run.

### Forensic Vaulting
To prevent **Database Drift** from breaking certifications:
1.  **T_end**: The run completes.
2.  **Snapshot**: The `ForensicCollector` takes an absolute image of all signs (logs, DB files, world state).
3.  **Vaulting**: These files are moved into the immutable `runs/<run_id>/forensics/` vault.
4.  **Certification**: The VC (Verification Certificate) is issued against the **Vaulted Snapshot**, not the "live" database. This ensures the audit trail remains valid even if the live environment is wiped or updated.

---

## Full Reference Implementation
Putting it all together into a production-grade file.

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
  },
  "workflow": {
    "nodes": [
      {
        "id": "verify_kyc",
        "task_description": "Verify User ID: 9988.",
        "required_tools": ["kyc_verify_api"],
        "expected_outcome": { "type": "typed_value", "data_type": "string", "value": "VALID" }
      }
    ],
    "edges": []
  },
  "evaluation": {
    "consensus": {
      "strategy": "Majority_Vote",
      "min_judges": 3,
      "judge_panel": ["gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]
    },
    "ija_threshold": 0.9
  }
}
```

> [!TIP]
> **Pro-Tip**: Always run `agentv aes validate your_file.json` after editing. It will catch schema errors before you waste money running a test with an invalid map!

