# Guide: Resource Telemetry & Gradient Analysis (v1.6.0)

AgentV 1.5.0 introduces **Hardware-Aware Forensics**, allowing you to monitor the physical footprint of agent execution. This is critical for detecting resource leaks (CPU/Memory/Disk) that lead to non-deterministic infrastructure failures.

## 1. The Resource Collector

The `SessionManager` now samples hardware metrics at every turn using `psutil`. These snapshots are bundled into the [Forensic Ledger](../../docs/src/content/docs/spec/forensic-ledger-schema.md) for post-run analysis.

### Captured Metrics
- **CPU (%)**: Process-level CPU utilization.
- **Memory (RSS MB)**: Resident Set Size (physical RAM) consumption.
- **Disk (%)**: Workspace filesystem saturation.

---

Traditional monitors only alert on hard crashes (e.g., OOM). For industrial audits, the **ResourceGradientAnalyzer** (available as an Enterprise extension) tracks the **rate of change** across turns.

### Identifying a Logic-Induced Leak
A sustained positive gradient (e.g., +2MB memory growth per turn) across 3+ consecutive turns indicates a memory leak in either the agent's logic or the world simulators. 

The analyzer will flag this as an `INFRA_OOM` precursor in the [Causal Chain](05_DRIFT_AND_TRIAGE.md/#3-automated-diagnostics-the-causal-chain-explain), even if the run successfully completes before hitting the hard limit.

---

## 3. Configuration

Telemetry is enabled by default in AES v1.4. Configuration for the industrial samplers is located in `config.yaml`:

```yaml
forensics:
  telemetry_sampling_interval: 1.0  # seconds
  capture_disk_metrics: true
```

## 4. Troubleshooting Precursors

When you see a `Resource Alert` in the console:
1.  Check the **Causal Chain** to see if the leak correlates with a [Strategic Loop](05_DRIFT_AND_TRIAGE.md).
2.  Use `agentv explain --run-id <id>` to see the exact turn where the gradient began its sustained ascent.
3.  Investigate either the agent's retry logic or the simulator's resource management (e.g., leaking file handles).
