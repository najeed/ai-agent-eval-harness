# Specification: Stratified Failure Taxonomy (v1.5.0)

To replace brittle, heuristic-based error string matching, AgentEval v1.5.0 implements an **Industrial-Grade Forensic Taxonomy Engine**. This system provides pluggable, hierarchical classification of agent failures, enabling forensic-grade root-cause diagnostics and causal-chain attribution.

## 1. Classification Hierarchy

Failures are categorized into four primary industrial domains:

| Category | Description | Industry Alignment |
| :--- | :--- | :--- |
| **INFRASTRUCTURE** | Simulator, network, or environment errors. | Reliability engineering |
| **LOGIC** | Reasoning errors, loops, or planning failures. | Cognitive assessment |
| **POLICY** | Violations of explicit tool or safety guardrails. | Governance & Compliance |
| **SECURITY** | Unauthorized access, data leaks, or PII breaches. | Cyber-security / Privacy |

---

## 2. Pluggable Analyzer Architecture

AgentV 1.5.0 transitions from a monolithic triage engine to a **Forensic Analyzer Registry**. Every diagnostic logic is encapsulated in an analyzer that implements the `BaseForensicAnalyzer` interface.

### Baseline vs. Enterprise Analyzers
- **Core (Baseline)**: Regex-based PII matching, cyclical turn repetition, and protocol sequence verification.
- **Enterprise (High-Fidelity)**: Semantic clustering of strategies, sustained resource gradient tracking, and state-action intent validation.

---

## 3. Forensic Triage & Causal Attribution

When a failure occurs, the engine performs a stratified analysis by executing all registered analyzers against the [Forensic Ledger](forensic_ledger_schema.md):

1.  **State Layer**: Compares state-delta snapshots (SHA-256) across turns.
2.  **Telemetry Layer**: Scans hardware resource gradients (CPU/Mem/Disk) for leaks via `psutil`.
3.  **Audit Layer**: Correlates events into a **Causal Chain**.

### Causal Chain Attribution
The engine distinguishes between the **Root Cause (Trigger)** and the **Terminal Status (Symptom)**. The Causal Chain provides a timestamped ledger of forensic alerts that leads to the final failure.

---

## 4. NIST AI-100-1 Mapping

This taxonomy is mapped directly to the **NIST AI-100-1** trustworthiness framework to support industrial certification:

- **Reliability** → Infrastructure Failures & Resource Gradients.
- **Safety** → Policy Failures.
- **Explainability** → Logic Failures (via Causal Chain).
- **Security & Privacy** → Security Failures.

> [!IMPORTANT]
> **Extensiblity**: Developers can register specialized forensic analyzers via the `on_diagnose_failure` plugin hook.
