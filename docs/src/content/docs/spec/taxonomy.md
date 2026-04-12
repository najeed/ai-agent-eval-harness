---
title: Triage Engine Specification
description: Authoritative technical reference for the AES v1.5.0 Triage Engine and Industrial Failure Taxonomy.
---

The **Triage Engine** is the primary diagnostic layer of AgentV, responsible for classifying agentic deviations into actionable failure codes. In AES v1.5.0, the engine has transitioned to a **Registry-Based Plugin Architecture**, allowing for lean baseline heuristics and high-fidelity Enterprise diagnostics.

## 🏗️ Architecture Overview

The Triage Engine follows a tiered diagnostic pipeline:

1.  **Baseline Heuristics (Core)**: Zero-latency regular expression and procedural checks (e.g., Protocol Parity, Cyclical Loops).
2.  **Registry-Based Analyzers**: Dynamic diagnostic modules registered via the `on_diagnose_failure` hook.
3.  **High-Fidelity Intelligence (Enterprise)**: Heavy analyzers using NLP clustering, hardware telemetry gradients, and intent-verification.

---

## 🏷️ Industrial Failure Categories

All failures are classified using the `FailureCategory` standard. These codes are designed to provide absolute clarity for both developers and compliance auditors.

### Infrastructure (`INFRA_`)
| Code | Trigger |
| :--- | :--- |
| `INFRA_TIMEOUT` | The evaluation run exceeded the global or task-level time budget. |
| `INFRA_CONNECTION_FAILED` | Network or service-level disruption preventing interaction. |
| `INFRA_OOM` | Out-of-Memory condition detected in the sandbox or agent process. |
| `INFRA_DISK_QUOTA` | Workspace disk usage exceeded allowed limits. |
| `INFRA_DOCKER_FAILURE` | Containerization layer disruption (e.g., daemon crash). |

### Logic & Reasoning (`LOGIC_`)
| Code | Trigger |
| :--- | :--- |
| `LOGIC_STALL` | The agent repeated the same logic for more than 10 turns without progress. |
| `LOGIC_REFUSAL` | The agent explicitly refused to perform the task (often due to safety alignment). |
| `LOGIC_PLANNING_ERROR` | A flaw in the agent's strategy led to a dead-end or invalid state. |
| `LOGIC_STATE_MISMATCH` | Contradiction between agent intent and actual environment effects. |

### Policy & Security (`POLICY_` / `SECURITY_`)
| Code | Trigger |
| :--- | :--- |
| `POLICY_HALLUCINATION` | The agent attempted to use non-existent tools or data. |
| `SECURITY_PII_LEAK` | Triggered when Personally Identifiable Information is detected in agent output. |
| `SECURITY_UNAUTHORIZED_ACCESS` | The agent attempted to access unauthorized namespaces or files. |
| `SECURITY_SANDBOX_ESCAPE` | Critical breach where the agent attempted to jailbreak the sandbox. |

---

## 🔒 PII Detection & Security Compliance

AgentV includes a high-fidelity PII scanner designed for industrial compliance (GDPR, HIPAA, PCI DSS). The engine uses a multi-pattern registry to detect sensitive data before it is persisted to the [Forensic Ledger](/spec/forensic-ledger-schema/).

### Pattern Registry
| Type | Standards | Description |
| :--- | :--- | :--- |
| **National** | GDPR | National IDs (SSN, Aadhar, Passport numbers). |
| **Financial** | PCI DSS | Credit card numbers, CVV, IBAN, and bank accounts. |
| **Medical** | HIPAA | MRNs (Medical Record Numbers) or Insurance IDs. |
| **Contact** | GDPR | Emails, physical addresses, and phone numbers. |
| **Digital** | GDPR | IP Addresses, MAC Addresses, and social handles. |
| **Crypto** | FinCEN | Bitcoin (bc1) and Ethereum (0x) wallet addresses. |

> [!IMPORTANT]
> When PII is detected, the engine emits a `SECURITY_PII_LEAK` event. In Enterprise environments, these values are automatically redacted in the visual console while being retained as encrypted hashes in the forensic audit trail.

---

## 🔬 Baseline Analyzers (Core)

The Core harness registers two authoritative analyzers by default:

### 1. ProtocolAnalyzer
Maintains **Protocol Affinity** by verifying that the agent stays within the interaction limits defined in the tool registry. It detects state-divergence when the environment snapshot doesn't match the expected structural effect of an action.

### 2. LoopAnalyzer
Detects **Cyclical Reasoning**. It uses a logic-aware window (default: 10 turns) to identify if an agent is stuck in a repetitive loop (e.g., a "Try-Hard" loop with slightly varied parameters but identical results).

---

## 🚀 Extending with Plugins

To add custom diagnostic depth, register a `BaseForensicAnalyzer` using the `on_diagnose_failure` hook.

```python
# MyForensicPlugin.py
def on_diagnose_failure(self, taxonomy):
    taxonomy.register_analyzer(MyCustomLogicAnalyzer())
```

For detailed implementation patterns, see the [Custom Forensic Analyzers](/extender/forensic-analyzers/) guide.
