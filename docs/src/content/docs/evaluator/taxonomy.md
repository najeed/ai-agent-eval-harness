---
title: Failure Taxonomy
description: NIST-aligned failure registry for forensic agent diagnostics.
---

To replace brittle, heuristic-based error matching, AgentV implements a formal **Stratified Failure Taxonomy**. This hierarchical classification enables forensic-grade root-cause diagnostics and NIST alignment.

## 🏛️ Classification Hierarchy

Failures are categorized into four primary industrial domains:

| Category | Description | Industry Alignment |
| :--- | :--- | :--- |
| **INFRASTRUCTURE**| Simulator, network, or environment errors. | Reliability Engineering |
| **LOGIC** | Reasoning errors, loops, or planning failures. | Cognitive Assessment |
| **POLICY** | Violations of explicit tool or safety guardrails. | Governance & Compliance |
| **SECURITY** | Unauthorized access, data leaks, or PII breaches. | Security & Privacy |

---

## 📋 The core Enum Registry

The following Enums are the first-class failure codes emitted by the evaluation engine.

### Infrastructure Failures
- `INFRA_SIMULATOR_EXCEPTION`: Internal 500 error in a World Shim (e.g., Database crash).
- `INFRA_TIMEOUT`: Evaluation exceeded the `EVAL_MAX_TURNS` or wall-clock limit.
- `INFRA_CONNECTION_FAILED`: Agent adapter could not reach the target endpoint.
- `INFRA_RESOURCE_EXHAUSTED`: Hardware usage (CPU/RAM) spiked during a critical tool call.

### Logic Failures
- `LOGIC_STALL`: Agent detected in a reasoning loop (multi-turn repetition).
- `LOGIC_REFUSAL`: Agent explicitly refused a valid mission task.
- `LOGIC_PLANNING_ERROR`: Agent logic diverged from the required [AES DAG Path](/evaluator/aes-spec/).
- `LOGIC_STATE_STALL`: The environment state failed to change despite the agent reporting success.

### Policy Failures
- `POLICY_VIOLATION`: Agent attempted an action blocked by a scenario-level guardrail.
- `POLICY_HALLUCINATION`: Agent attempted to use a tool that does not exist in the VFS.
- `POLICY_DACON_LEAK`: Detected exposure of internal system prompts or logic.

### Security Failures
- `SECURITY_PII_LEAK`: Agent exposed sensitive personal information (emails, phone numbers).
- `SECURITY_UNAUTHORIZED_ACCESS`: Tool call made with incorrect PBAC permissions.
- `SECURITY_SANDBOX_ESCAPE`: (Critical) Attempted filesystem access outside the managed workspace.

---

## 🔍 Forensic Triage

When a failure occurs, the `TriageEngine` performs a three-layer analysis to identify the "Patient Zero" step:

1.  **State Layer**: Compares the physical VFS delta against the scenario ground truth.
2.  **Telemetry Layer**: Scans framework events for node transition crashes.
3.  **Registry Layer**: Correlates the error with a known Enum from this taxonomy.

## 🛡️ NIST AI-100-1 Mapping

This taxonomy supports industrial certification by mapping directly to NIST AI-100-1 dimensions:
- **Reliability** → Infrastructure Failures.
- **Safety** → Policy Failures.
- **Explainability** → Logic Failures.
- **Security & Privacy** → Security Failures.
