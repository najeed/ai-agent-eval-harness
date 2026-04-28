---
title: Agent Eval Specification (AES)
description: The foundational standard for shareable, multi-turn, and forensic agent benchmarks.
---

AES is an industrial-grade specification used to define benchmarks that are framework-agnostic, deterministic, and audit-ready.

## 1. Design Philosophy

- **Human Readable**: Standardized JSON/YAML schema.
- **Framework Agnostic**: One spec to evaluate LangGraph, CrewAI, AutoGen, or custom agents.
- **CI/CD Ready**: Native validation via JSON Schema and the `agentv lint` tool.
- **Deterministic DAGs**: Task dependencies are defined as nodes and edges in a directed acyclic graph.

---

## 2. Core Schema (v1.4)

### Metadata (`metadata`)
Stricter requirements to ensure environment reproducibility and forensic traceability.
- **`id`**: (Required) Global unique forensic identifier (slug-style).
- **`capabilities`**: (Required) Skills required to solve the scenario (e.g., `web_navigation`, `sql_generation`).
- **`standards_registry`**: (Optional) Regulatory mapping (e.g., `ISO_20022`, `NIST`).
- **`aes_version`**: Must be set to `1.4`.

### DAG Workflow (`workflow`)
AES v1.4 replaces linear tasks with a **Workflow DAG**, allowing for complex, multi-stage evaluations.

```json
"workflow": {
  "nodes": [
    {
      "id": "t1",
      "task_description": "Verify customer identity.",
      "success_criteria": [{"metric": "policy_compliance", "threshold": 1.0}]
    },
    {
      "id": "t2",
      "task_description": "Update credit limit in CRM.",
      "success_criteria": [{"metric": "state_verification", "threshold": 1.0}]
    }
  ],
  "edges": [
    { "from": "t1", "to": "t2" }
  ]
}
```

---

## 3. High-Fidelity Infrastructure

### World Shims
Scenarios can explicitly mount the required environment simulators.

```json
"enabled_shims": ["database", "stripe", "security", "slack"]
```

### Path Decoupling
AES supports relative path resolution for datasets (e.g., `./data.csv`), ensuring that benchmark bundles are portable across different filesystems.

---

## 4. Forensic DNA & Trust

### Environmental DNA Snapshot
Every execution captures an immutable **Provisioning Hash** of the final merged registry state. This ensures that the agent was tested against the sanctioned environment configuration.

### Behavioral DNA
A cryptographic signature (Ed25519) that binds the execution trace (`run.jsonl`) and all sidecar artifacts (reports, plots) to the scenario's DAG structure.

:::important
**Certification Rule**: A trace is only "Forensically Valid" if the `harness_version` supports the requested `aes_version` and the `provisioning_hash` matches the sanctioned baseline.
:::

---

## 5. Industrial Standards Alignment
AES natively supports global industrial standards including:
- **Finance**: ISO 20022
- **Healthcare**: HL7 FHIR
- **Manufacturing**: Digital Twins
- **Trust**: NIST AI-100-1
