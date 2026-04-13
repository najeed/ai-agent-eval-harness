# Guide: Drift Management & Deep Forensics Triage (v1.5.0)

This guide details how to use the Semantic Bridge features and the pluggable **Deep Forensics** engine to analyze agent failures.

## 1. Drift Importer (`import-drift`)

The Drift Importer allows you to convert production traces (agent/user interaction logs) into reusable evaluation scenarios. This is critical for building regression suites from real-world "drift."

### Usage
```bash
agentv import_drift --input path/to/trace.json --industry telecom
```

### Result
A new scenario file is created in `industries/[industry]/scenarios/drift-[hash].json`, containing the original history as `ground_truth_history`.

---

## 2. Pluggable Triage Engine

AgentV 1.5.0 introduces the **Identity-Signed Forensic Analyzer Registry**. Failure diagnostics are no longer a black-box heuristic; they are a series of pluggable analyzers that inspect the [Forensic Ledger](../../docs/src/content/docs/spec/forensic-ledger-schema.md).

### Diagnostic Triage Tags
| Tag | Description | Identity Anchoring |
| :--- | :--- | :--- |
| `INFRA_TIMEOUT` | Exceeded wall-clock limits (Hardware telemetry gradient). | Step-Back to Agent Stimulus |
| `POLICY_VIOLATION` | Explicit deviation from safety/identity boundaries. | Detection Point |
| `LOGIC_STATE_STALL` | No measurable state progress detected across 3+ turns. | Trigger Point |
| `INFRA_CONNECTION_FAILED` | Network or platform unavailability. | Step-Back to Agent Turn |

---

## 3. Automated Diagnostics: The Causal Chain (`explain`)

While triage applies categorical tags, the `explain` command now performs a **Causal Attribution** analysis to identify the Root Cause.

### Causal Attribution
The engine distinguishes between the **Root Cause (Trigger)** and the **Terminal Status (Symptom)**.

**Robust Step-Back Scan**: In v1.5.2, the triage engine performs a backward identity search to anchor infrastructure or metric faults to the preceding agent turn.

**Example**:
- **Root Cause**: `LOGIC_PLANNING_ERROR` (Circular Loop found via Step-Back)
- **Manifestation**: `INFRA_TIMEOUT`

### Forensic Features
- **Deterministic Trail**: Every failure is traced via the **Causal Chain**, a timestamped ledger linking forensic alerts.
- **Resource Gradient Analysis**: Identifies hardware pressure (CPU/RAM spikes) as precursors to failure. See the [Resource Monitoring Guide](08_RESOURCE_MONITORING.md).
- **State-Action Integrity**: Contradicts agent claims against physical state-delta reality.

> [!TIP]
> **Industrial Replay**: You can export the full Forensic Ledger and causal chain for offline audit or replay using the `--export forensic` flag.

