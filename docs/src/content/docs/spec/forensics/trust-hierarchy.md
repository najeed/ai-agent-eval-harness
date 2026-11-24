---
title: Trust Hierarchy & State Isolation
description: Technical specification for agent-environment trust gating and forensic state protection.
---

Metric access depends on the source registered in MetricRegistry and the
PluginManager provenance record for that source.

| Source | Mutable history/state hydration | Extra context |
| --- | --- | --- |
| `CORE` | Original values | `session_metadata`, `forensic_telemetry` |
| Non-CORE with trusted provenance | Deep copies of requested dict/list values | `session_metadata`, `forensic_telemetry` |
| Other non-CORE sources | Deep copies of requested dict/list values | Extra trusted context omitted |

Trust is recorded from the plugin loading origin. An arbitrary registry JSON
`trusted` field does not establish that provenance. This table describes metric
parameter hydration in SessionMetricsCalculator, not a universal sandbox around
every plugin or analyzer.

EvaluationContext is a frozen dataclass. Its scenario, metadata and global-state
mappings are deep-copied and wrapped in MappingProxyType at the top level; nested
values remain mutable. TurnContext converts list history into a deep-copied tuple
of dictionaries; the tuple does not recursively freeze those dictionaries.
`plugin_data` intentionally remains mutable. These mechanisms prevent accidental
changes through common APIs; in-process Python extensions still execute with the
host process privileges. Cryptographic trace commitments and provider sealing
have separate integrity contracts.
