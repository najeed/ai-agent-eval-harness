---
title: Commander's Taxonomy
description: The NIST-aligned hierarchical classification system for industrial AI agent failures.
---

import { Badge } from '@astrojs/starlight/components';

To replace brittle, heuristic-based error matching, MultiAgentEval implements a formal, **NIST-aligned Failure Registry**. This system provides a stratified classification of agent failures, enabling forensic-grade root-cause diagnostics for **Industry Evaluators**.

---

## 1. Classification Domains

Failures are categorized into four primary industrial domains to support NIST AI RMF certifications:

| Category | Description | Industry Axis |
| :--- | :--- | :--- |
| **INFRASTRUCTURE** | Environment, network, or hardware errors. | <Badge text="Reliability" variant="note" /> |
| **LOGIC** | Reasoning, loops, or planning failures. | <Badge text="Effectiveness" variant="success" /> |
| **POLICY** | Violations of safety or tool-usage guardrails. | <Badge text="Governance" variant="caution" /> |
| **SECURITY** | Data leaks, unauthorized access, or PII breaches. | <Badge text="Security/Privacy" variant="danger" /> |

---

## 2. Global Failure Registry

First-class failure codes emitted by the engine for audit reports:

### 🛡️ Infrastructure
- `INFRA_SIMULATOR_EXCEPTION`: Internal 500 error in a World Shim (e.g., Database crash).
- `INFRA_TIMEOUT`: Evaluation exceeded the `EVAL_MAX_TURNS` or wall-clock limit.
- `INFRA_CONNECTION_FAILED`: Agent adapter could not reach the target endpoint.

### 🧠 Logic & Reasoning
- `LOGIC_STALL`: Agent detected in a reasoning loop (multi-turn repetition).
- `LOGIC_REFUSAL`: Agent explicitly refused a valid mission task.
- `LOGIC_PLANNING_ERROR`: Agent logic diverged from the required industrial DAG path.

### ⚖️ Policy & Compliance
- `POLICY_VIOLATION`: Agent attempted an action blocked by a scenario-level guardrail.
- `POLICY_HALLUCINATION`: Agent attempted to use a tool that does not exist in the Sandbox.
- `POLICY_DACON_LEAK`: Detected exposure of internal system prompts or confidential logic.

### 🔒 Security & Privacy
- `SECURITY_PII_LEAK`: Agent exposed sensitive personal information in its response.
- `SECURITY_UNAUTHORIZED_ACCESS`: Tool call made with incorrect PBAC permissions.
- `SECURITY_SANDBOX_ESCAPE`: **Critical Violation**: Attempted filesystem access outside the managed workspace.

---

## 3. Forensic Triage Engine

When a failure occurs, the Triage Engine performs a tiered audit to identify **Patient Zero**:

1.  **State Layer**: Compares the physical VFS delta against the scenario ground truth.
2.  **Telemetry Layer**: Scans framework-level event streams for crash signatures.
3.  **Registry Layer**: Correlates findings with the global enum classification.

**Outcome**: A forensic report identifying the exact step, turn, and tool-call responsible for the failure cascade.

---

## 4. Certification Alignment

This taxonomy maps directly to global standards to support official platform certification:

- **NIST AI-100-1**: Reliability, Safety, and Security mapping.
- **ISO/IEC 42001**: Auditability for AI Management Systems.
- **GDPR**: Alignment with Security and Privacy failure classifications.

> [!TIP]
> **Extensibility**: Platform Extenders can register custom failure codes via the `on_discover_failures` plugin hook to handle sector-specific edge cases.
