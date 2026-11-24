---
title: Resource Telemetry & Monitoring
description: Tracking hardware metrics and resource gradients in real-time.
---

SessionManager samples resource telemetry at explicit execution call sites when
psutil is available. This describes the harness process, not the complete
resource footprint of an external agent.

| Field | Measurement |
| --- | --- |
| `timestamp` | Capture time as Unix epoch seconds |
| `cpu_percent` | `psutil.Process(os.getpid()).cpu_percent()` for the harness PID |
| `rss_mb` | Harness resident memory in MiB |
| `vms_mb` | Harness virtual memory in MiB |
| `disk_usage_percent` | Usage percentage of the filesystem containing the current working directory |

Child processes and remote agents are not aggregated. Disk usage is for the
filesystem, not the amount consumed by one workspace. Sampling is tied to
session call sites rather than a guaranteed periodic interval; short operations
can occur between samples, and unavailable psutil/capture failures can leave gaps.

## Configuration and analysis

Core capture does not consume a `forensics.telemetry` config.yaml block with
`interval_ms`, `capture_on_tool_call` or `leak_threshold_mb_per_turn`. Implement
custom sampling or resource-gradient diagnostics in a plugin if needed, and
document its settings separately. A rising memory trend is an observation, not
automatic proof of a leak or of a remote model's resource usage.

Samples are recorded under `resource_telemetry` in the
[forensic ledger](/spec/forensic-ledger-schema/). Trusted metric hydration exposes
them as `forensic_telemetry`; access and copying are described in the
[trust contract](/spec/forensics/trust-hierarchy/).
