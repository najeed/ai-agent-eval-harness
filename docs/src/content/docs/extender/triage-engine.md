---
title: Triage Engine & Forensic Analyzers
description: Advanced failure diagnostics via the pluggable forensic analyzer architecture.
---

AgentV 1.5.0 transforms failure diagnosis from a monolithic heuristic engine into a **High-Fidelity Forensic Pipeline**. 

## 1. The Forensic Diagnostic Pipeline

Failure diagnosis is no longer a single "scan." It is an ordered execution of **Forensic Analyzers** that operate on the [Forensic Ledger](/spec/forensic-ledger-schema/).

| Step | Layer | Description |
| :--- | :--- | :--- |
| **1** | **Pipeline** | Detects terminal outcomes (Success, Partial Pass). |
| **2** | **Infrastructure** | Scans telemetry for simulator crashes, OOMs, and timeouts. |
| **3** | **Protocol** | Verifies [handshake sequences](/spec/forensic-ledger-schema/#protocol-sequences). |
| **4** | **Behavioral** | Analyzes agent DNA for loops and hallucinations. |
| **5** | **Custom** | Executes third-party analyzers registered via [Plugins](/extender/plugins/). |
| **6** | **Decision** | Finalizes the Root Cause via the Weighted Evidence Model. |

---

## 2. Weighted Evidence & Ranking

In AES v1.5.0, the triage engine no longer returns the first failure it finds. Instead, it collects **Evidence** from multiple analyzers and uses a weighted scoring system to resolve conflicts.

### Ranking Logic
Each diagnostic trigger is assigned a **Global Rank** (0-10) and a **Confidence Score**. 

1. **Primary Root Cause**: The trigger with the highest combined Rank and Confidence.
2. **Contributing Factors**: Secondary triggers that occurred but are ranked lower (e.g., an Infrastructure Timeout that was caused by an upstream Agent Stall).

> [!IMPORTANT]
> Infrastructure and Policy violations (e.g., OOM or PII Leaks) are always weighted higher than behavioral symptoms (e.g., Stalls), as they represent deterministic execution boundaries.

The triage engine is refactored for **Core Extensibility**. Every diagnostic logic is encapsulated in an analyzer that implements the `BaseForensicAnalyzer` interface.

- **Core Analyzers**: Baseline regex matching, cyclical loop detection, and basic protocol checks.
- **Enterprise Analyzers**: High-fidelity semantic clustering (LLM), sustained resource gradient tracking, and state-action intent verification.

> [!TIP]
> You can extend the triage engine by writing your own analyzer. See the [Custom Forensic Analyzers](/extender/forensic-analyzers/) guide.

---

## 3. Causal Chain Attribution

AgentV 1.5.0 distinguishes between the **Root Cause (Trigger)** and the **Terminal Status (Symptom)**.

- **Trigger**: The specific mistake or anomaly (e.g., "Semantic Loop detected").
- **Symptom**: The final state of the task (e.g., "INFRA_TIMEOUT").

Every classification is documented in a **Causal Chain**, allowing auditors to trace the exact lineage of a failure from the first logic divergence to the final crash.

---

## 4. Forensic Affinity & Identity Authority (AES v1.5.0)

To maintain industrial-grade stability, all triage operations must be anchored to an authoritative identity:

- **Zero-Inference Resolution**: The Triage Engine requires an explicit `run_id` to initialize diagnostics. Speculative inference from parent directories is prohibited to prevent forensic cross-contamination.
- **Vault Affinity**: Diagnostics are only performed on traces within valid industrial vaults (`runs/<run_id>/run.jsonl`) or the master log. Traces in shared temporary space are ineligible for audit-grade triage.
- **Manifest Persistence**: Root cause classifications are persisted directly into the `run_manifest.json` as signed evidence, creating an immutable link between the diagnostic outcome and the forensic identity.

## 5. Forensic Data Sinks

The triage engine leverages three primary data sinks captured by the `SessionManager`:
1.  **State Snapshots**: Content-hashed fingerprints of the environment at each turn.
2.  **Resource Telemetry**: Real-time CPU, RAM, and Disk metrics.
3.  **Protocol Trace**: A sequence of FSM transitions recorded during execution.

For technical details on these fields, refer to the [Forensic Ledger Specification](/spec/forensic-ledger-schema/).
