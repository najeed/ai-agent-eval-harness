# Agent Evaluation Specification (AES) v1.4

The **Agent Evaluation Specification (AES)** is the formal standard for defining executable AI benchmarks. It ensures that evaluations are deterministic, forensically traceable, and portable across different execution environments.

---

## 1. Core Principles
- **Schema First**: Validatable via JSON Schema.
- **Deterministic DAGs**: Support for multi-stage workflow execution with dependency gating.
- **Path Decoupling**: Fully portable assets using relative path resolution.

---

## 2. Root Structure
A valid AES scenario must contain the following top-level keys:

| Key | Type | Description |
| :--- | :--- | :--- |
| **`aes_version`** | `float` | Must be `1.4`. |
| **`metadata`** | `object` | Authoritative identity and industry tags. |
| **`workflow`** | `object` | The DAG of tasks and dependencies. |
| **`evaluation`** | `object` | Judging consensus and validation rules. |
| **`enabled_shims`** | `array` | Explicit whitelist of world simulators. |
| **`initial_state`** | `object` | (Optional) Global state injection for all shims. |
| **`environmental_snapshot`** | `object` | (Optional) Forensic capture of pre-run environment DNA. |

---

## 3. Metadata Block (`metadata`)
The metadata block acts as the **Authoritative Identity Vault** for the scenario.

- **`id`**: (Required) Global unique forensic identifier (e.g., `fin-loan-001`).
- **`name`**: (Required) Human-readable title.
- **`compliance_level`**: (Required) Regulatory tier (`Standard`, `Gold`, `Regulatory_Audit`).
- **`industry`**: (Recommended) Sector mapping (e.g., `finance`, `healthcare`).
- **`capabilities`**: (Recommended) A list of specific agentic skills required (e.g., `sql_generation`). These are used for **Agent Routing** but do not drive environment provisioning.

---

## 4. Workflow DAG (`workflow`)
Scenarios define a directed acyclic graph (DAG) of `nodes` and `edges`.

### Nodes (Tasks)
Each node represents an atomic task for the agent.
- **`id`**: Unique identifier for the task within the scenario.
- **`task_description`**: The prompt or instruction sent to the agent.
- **`required_tools`**: (Optional) List of specific shim tools the agent is expected to use.
- **`expected_outcome`**: (Optional) A list of contract targets used to verify success.
  - **`target`**: (Required) A shim-path or tool assertion (e.g., `shim:database.users`).
  - **`expected`**: (Required) The expected value or success criteria.

---

## 5. Evaluation Block (`evaluation`)
The evaluation block defines how the agent's performance is judged and validated across attempts.

### Consensus Strategy (`consensus`)
Used for batch runs or pluralistic judging.
- **`strategy`**: The mathematical rule for success (`Majority_Vote`, `Absolute_Unanimity`, `Weighted_Average`).
- **`min_judges`**: The minimum number of judges required for a valid consensus.
- **`judge_panel`**: (Optional) List of specific judge model IDs to utilize.

### Metrics & Thresholds
- **`ija_threshold`**: (0.0 to 1.0) The Inter-Judge Agreement threshold required to certify a result.

---

## 6. World Shims (`enabled_shims`)
AES scenarios declare their required environment simulators. This allows the engine to provision isolated "jails" for the evaluation.

### Activation Hierarchy
- **Strict Discovery Mode**: If `enabled_shims` is **omitted**, the engine auto-activates only the shims relevant to the `workflow` contract.
- **Explicit Whitelist**: If `enabled_shims` is **provided**, it acts as a hard forensic boundary. Only shims in this list will be activated.

---

## 7. Versioning & Provenance
To support high-stakes industrial audits, AgentV decouples the **Standard Specification** from the **Execution Engine**.

| Component | Example | Description |
| :--- | :--- | :--- |
| **`aes_version`** | `1.4` | The version of this JSON schema. |
| **`harness_version`** | `1.6.0` | The version of the engine executing the spec. |

> [!IMPORTANT]
> **Industrial Rule**: A single `aes_version` can be satisfied by multiple `harness_version` builds, but a trace is only **Forensically Valid** if the engine explicitly supports the requested specification version.

---

📖 For execution details, CLI commands, and forensic auditing, see the [Harness User Guide](./05_HARNESS_USER_GUIDE.md).
