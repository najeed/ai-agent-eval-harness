---
title: Triage Engine Specification
description: Authoritative technical reference for the AES v1.4 Triage Engine and Industrial Failure Taxonomy.
---

The **Triage Engine** is the primary diagnostic layer of AgentV, responsible for classifying agentic deviations into actionable failure codes. In AES v1.4, the engine has transitioned to a **Registry-Based Plugin Architecture**, allowing for lean baseline heuristics and high-fidelity Enterprise diagnostics.

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
| `INFRA_SIMULATOR_EXCEPTION` | Internal error or unhandled exception within a World Shim (e.g., Database crash). |
| `INFRA_TIMEOUT` | The evaluation run exceeded the global or task-level time budget. |
| `INFRA_CONNECTION_FAILED` | Network or service-level disruption preventing interaction with the agent endpoint. |
| `INFRA_OOM` | Out-of-Memory condition detected in the sandbox or agent process. |
| `INFRA_DISK_QUOTA` | Workspace disk usage exceeded allowed limits. |
| `INFRA_SANDBOX_FAILURE` | Containerization or isolation layer disruption (e.g., daemon crash). |
| `INFRA_RESOURCE_EXHAUSTED` | Hardware spike (CPU > 90% or OOM) correlated with tool failure. |

### Logic & Reasoning (`LOGIC_`)
| Code | Trigger |
| :--- | :--- |
| `LOGIC_STALL` | The agent repeated the same logic for more than 10 turns without progress. |
| `LOGIC_REFUSAL` | The agent explicitly refused to perform the task (often due to safety alignment). |
| `LOGIC_PLANNING_ERROR` | A flaw in the agent's strategy led to a dead-end or invalid state. |
| `LOGIC_STATE_MISMATCH` | Contradiction between agent intent and actual environment effects. |
| `LOGIC_STATE_STALL` | Environment state remains unchanged despite agent tool calls (Fuzzy No-Op). |
| `LOGIC_UNCERTAINTY` | Agent expresses confusion or doubt in thoughts/utterances. |
| `LOGIC_ABANDONMENT` | Agent issues a 'finished' status but lacks task metrics (Soft Quit). |

### Policy & Security (`POLICY_` / `SECURITY_`)
| Code | Trigger |
| :--- | :--- |
| `POLICY_VIOLATION` | Agent attempted an action blocked by a scenario-level guardrail. |
| `POLICY_HALLUCINATION` | The agent attempted to use non-existent tools or data. |
| `POLICY_DACON_LEAK` | Detected exposure of internal system prompts or logic. |
| `SECURITY_PII_LEAK` | Triggered when Personally Identifiable Information is detected in agent output. |
| `SECURITY_UNAUTHORIZED_ACCESS` | The agent attempted to access unauthorized namespaces or files. |
| `SECURITY_SANDBOX_ESCAPE` | Critical breach where the agent attempted to jailbreak the sandbox. |

### Forensic Parity (`PARITY_`)
| Code | Trigger |
| :--- | :--- |
| `PARITY_STATE_DIVERGENCE` | High-fidelity mismatch between expected and actual VFS/Shim state. |
| `PARITY_PROTOCOL_VIOLATION` | Agent diverged from the mandated interaction protocol (e.g., HTTP vs SSE). |

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

:::important
When PII is detected, the engine emits a `SECURITY_PII_LEAK` event. In Enterprise environments, these values are automatically redacted in the visual console while being retained as encrypted hashes in the forensic audit trail.
:::

---

## 🔬 Baseline Analyzers (Core)

The Core harness registers two analyzers by default:

### 1. ProtocolAnalyzer
Maintains **Protocol Affinity** by verifying that the agent stays within the interaction limits defined in the tool registry. It detects state-divergence when the environment snapshot doesn't match the expected structural effect of an action.

### 2. LoopAnalyzer
Detects **Cyclical Reasoning** and **Logical Stalls**.
- **Fuzzy Matching**: Identifies rephrased agent thoughts that indicate circular planning.
- **Action Normalization**: Strips command flags (e.g., `git commit -m`) to catch stalls where an agent repeats the same base action with jittered parameters.
- **Cycle Detection**: Uses a logic-aware window (default: 10 turns) to identify if an agent is stuck in an A -> B -> A loop.

---

## 🚀 Extending with Plugins

To add custom diagnostic depth, register a `BaseForensicAnalyzer` using the `on_diagnose_failure` hook.

```python
# MyForensicPlugin.py
def on_diagnose_failure(self, taxonomy):
    taxonomy.register_analyzer(MyCustomLogicAnalyzer())
```

For detailed implementation patterns, see the [Custom Forensic Analyzers](/extender/forensic-analyzers/) guide.
