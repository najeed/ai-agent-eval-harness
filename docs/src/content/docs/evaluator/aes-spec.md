---
title: Agent Evaluation Specification (AES)
description: Technical reference for the AES v1.4 schema and the spec-to-eval hybrid parser.
---

The **Agent Evaluation Specification (AES)** is the formal standard used by AgentV to defineexecutable benchmarks. Version 1.4 introduces a **Hybrid Parsing Strategy** that allows evaluation suites to be generated directly from raw Product Requirement Documents (PRDs).

## 🏗️ The AES v1.4 Schema

An AES scenario is a JSON document that defines the environment, the tasks, and the success criteria.

```json
{
  "aes_version": 1.4,
  "metadata": {
    "id": "finance-fraud-v1",
    "name": "Finance Fraud Detection",
    "compliance_level": "Standard"
  },
  "industry": "Finance",
  "workflow": {
    "nodes": [
      {
        "id": "t1",
        "task_description": "Analyze account #1234 for recent fraudulent activity.",
        "success_criteria": [{"metric": "accuracy", "threshold": 0.95}]
      }
    ],
    "edges": []
  }
}
```

---

## 🤖 Spec-to-Eval Parser

The `spec-to-eval` command transforms Markdown PRDs into executable AES JSON. It balances deterministic precision with LLM-based flexibility.

### 1. Deterministic Structural Parser
A high-speed parser that recognizes standard enterprise Markdown patterns:

- **H1 Title**: Sets the `id`.
- **Metadata Block**: `**Industry:** Finance`.
- **Tools Section**: `## Tools` (Global tools for all tasks).
- **Tasks Section**: `## Tasks` or `## Test Cases`.
  - **H3 Task Headers**: `### 1. [Task Title]`
  - **Bullet Metadata**: `Expected Outcome`, `Tools`, and `Criteria`.

### 2. LLM Synthesis Fallback
If the structural parser fails to find tasks, the engine automatically triggers an LLM pass (Gemini 2.5 Flash) to synthesize the scenario from the PRD business logic.

```bash
[SpecParser] No tasks found via search. Synthesizing from rules...
```

---

## 🛡️ Robustness Features

- **Metadata Stripping**: Patterns like `(Expect: ...)` within a task description are automatically extracted to the `expected_outcome` field and cleaned from the main description.
- **Synonym Recognition**: "Test Cases", "Evaluation Steps", and "Tasks" are treated as equivalent headers.
- **Global Tool Injection**: Tools defined in a global `## Tools` section are inherited by all tasks unless explicitly overridden.

---

> [!NOTE]
> **Infrastructure Decoupling**: AES v1.4 decouples environment lifecycle management (setup/teardown) from the scenario JSON. These side-effects are managed by the execution engine's plugin architecture.

## 🚀 Workflow

To convert a PRD and backfill schema defaults:

```bash
agentv spec-to-eval \
  --input docs/specs/fraud_prd.md \
  --output scenarios/fraud.json \
  --fill-defaults \
  --force
```

> [!IMPORTANT]
> **Schema Validation**: Validated AES files are required for [Trust Protocol Certification](/auditor/trust-protocol/). Unauthorized modifications to a certified AES file will trigger a **Behavioral Drift** alert in Phase 5.
