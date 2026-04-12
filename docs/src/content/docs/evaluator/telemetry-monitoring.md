---
title: Resource Telemetry & Monitoring
description: Tracking hardware metrics and resource gradients in real-time.
---

AgentV 1.5.0 introduces native **Resource Telemetry**, allowing you to monitor the hardware footprint of your agents during evaluation. This is critical for detecting "silent" infrastructure failures like resource leaks, memory bloat, and disk quota precursors.

## 1. Monitored Metrics

The `SessionManager` captures the following hardware metrics at every agent turn and tool execution:

- **CPU Usage (%)**: The normalized CPU load of the hosting process and its children.
- **Memory (RSS MB)**: The resident set size (actual physical memory) consumed.
- **Virtual Memory (VMS MB)**: The total memory address space requested.
- **Disk Usage (%)**: The percentage of the workspace disk currently consumed.

---

## 2. Resource Gradients (Leak Detection)

Instead of just checking for a hard crash (e.g., OOM), the [ResourceGradientAnalyzer](/extender/triage-engine/#2-pluggable-analyzers-core-vs-enterprise) tracks the **Gradient** (rate of change) of these metrics.

### Identifying a Memory Leak
- **Normal**: Memory fluctuates as tools are loaded and unloaded.
- **Anomalous**: A sustained, positive linear gradient (e.g., +5MB per turn) across more than 3 turns, even during idle periods.

When a leak is detected, AgentV flags the session with a `LOGIC_STATE_STALL` or `INFRA_OOM` trigger in the [Causal Chain](/auditor/causal-chains/).

---

## 3. Configuration

Telemetry is enabled by default in the Industrial Edition. You can configure the capture interval and threshold in your `config.yaml`:

```yaml
forensics:
  telemetry:
    enabled: true
    interval_ms: 500
    capture_on_tool_call: true
    leak_threshold_mb_per_turn: 2.0
```

---

## 4. Viewing Telemetry Data

Hardware metrics are stored in the `resource_telemetry` field of the [Forensic Ledger](/spec/forensic-ledger-schema/).

In the **Visual Console**, you can view these metrics as a sparkline graph overlaying the agent's trajectory, allowing you to correlate logic spikes with hardware pressure in real-time.
