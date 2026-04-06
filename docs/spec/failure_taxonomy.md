# Specification: Stratified Failure Taxonomy (v1.3)

To replace brittle, heuristic-based error string matching, AgentEval v1.3.0 implements a formal, **NIST-aligned Failure Registry**. This system provides a stratified, hierarchical classification of agent failures, enabling forensic-grade root-cause diagnostics.

## 1. Classification Hierarchy

Failures are categorized into four primary industrial domains:

| Category | Description | Industry Alignment |
| :--- | :--- | :--- |
| **INFRASTRUCTURE** | Simulator, network, or environment errors. | Reliability engineering |
| **LOGIC** | Reasoning errors, loops, or planning failures. | Cognitive assessment |
| **POLICY** | Violations of explicit tool or safety guardrails. | Governance & Compliance |
| **SECURITY** | Unauthorized access, data leaks, or PII breaches. | Cyber-security / Privacy |

---

## 2. The Core Enum Registry

The following Enums are the first-class failure codes emitted by the engine:

### Infrastructure Failures
- `INFRA_SIMULATOR_EXCEPTION`: Internal 500 error in a World Shim (e.g., Database crash).
- `INFRA_TIMEOUT`: Evaluation exceeded the `EVAL_MAX_TURNS` or wall-clock limit.
- `INFRA_CONNECTION_FAILED`: Agent adapter could not reach the target endpoint.

### Logic Failures
- `LOGIC_STALL`: Agent detected in a reasoning loop (multi-turn repetition).
- `LOGIC_REFUSAL`: Agent explicitly refused a valid mission task.
- `LOGIC_PLANNING_ERROR`: High-Fidelity: Agent logic diverged from the required DAG path.

### Policy Failures
- `POLICY_VIOLATION`: Agent attempted an action blocked by a scenario-level guardrail.
- `POLICY_HALLUCINATION`: Agent attempted to use a tool that does not exist in the VFS.
- `POLICY_DACON_LEAK`: Detected exposure of internal system prompts or logic.

### Security Failures
- `SECURITY_PII_LEAK`: Agent exposed sensitive personal information in its response.
- `SECURITY_UNAUTHORIZED_ACCESS`: Tool call made with incorrect PBAC permissions.
- `SECURITY_SANDBOX_ESCAPE`: (Critical) Attempted filesystem access outside the managed workspace.

---

## 3. Forensic Triage & Isolation

When a failure occurs, the `TriageEngine` is triggered. It performs a three-layer analysis:

1.  **State Layer**: Compares the physical VFS delta against the scenario's ground truth.
2.  **Telemetry Layer**: Scans the `CHAIN_START` / `NODE_START` events for framework-level crashes (e.g., LangGraph node transitions).
3.  **Registry Layer**: Correlates the error with a known Enum from the Failure Registry.

The result is a **Patient Zero Identification**—the exact step, turn, and tool-call responsible for the cascade.

## 4. NIST AI-100-1 Mapping

This taxonomy is mapped directly to the **NIST AI-100-1** trustworthiness framework to support industrial certification:

- **Reliability** → Infrastructure Failures.
- **Safety** → Policy Failures.
- **Explainability** → Logic Failures (via Root Cause Isolation).
- **Security & Privacy** → Security Failures.

> [!IMPORTANT]
> **Extensibility**: Developers can register custom failure codes in the registry via the `on_discover_failures` plugin hook.
