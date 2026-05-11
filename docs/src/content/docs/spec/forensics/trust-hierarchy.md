---
title: Trust Hierarchy & State Isolation
description: Technical specification for agent-environment trust gating and forensic state protection.
---

To ensure that industrial evaluations are both secure and non-repudiable, AgentV implements a **Tiered Trust Model** and **Immutable State Isolation**. This prevents external plugins or untrusted metrics from corrupting the evaluation trajectory.

## 🛡️ 3-Tier Trust Hierarchy

The harness classifies all components (Metrics, Plugins, Analyzers) into three trust tiers. This determines their level of access to sensitive session metadata and hardware telemetry.

| Tier | Source | Permissions |
| :--- | :--- | :--- |
| **CORE** | Internal `eval_runner` | Full access to `session_metadata`, `resource_telemetry`, and internal buffers. |
| **TRUSTED** | Signed Member Plugins | Access to restricted system parameters. Requires cryptographic provenance. |
| **EXTERNAL** | Third-party / Ad-hoc | Restricted to sanitized `agent_summary` and isolated (copied) history. |

### Trust Gating in `session.py`

When a metric or plugin is invoked, the `SessionManager` checks its provenance:

```python
# [AES v1.6.0] Trust Gate for System Parameters
if is_trusted:
    context_map["session_metadata"] = self.session_metadata
    context_map["resource_telemetry"] = self.resource_telemetry
```

---

## 🧬 Conditional Deep-Copy Isolation

To prevent "Trajectory Pollution," AgentV enforces strict memory isolation. Untrusted components never receive a direct reference to the live session state.

### How it works:
1.  **Mutable Guard**: If a component is not marked as **CORE** and requests a mutable object (like `history` or `actual_state`), the harness automatically performs a `copy.deepcopy()`.
2.  **Performance Optimization**: Deep-copying is skipped for **CORE** components to minimize latency in high-frequency diagnostic loops.

### Implementation Pattern:
```python
def get_isolated(key, data, _params=params, _is_core=is_core):
    if key in _params and not _is_core and isinstance(data, (dict, list)):
        return copy.deepcopy(data)
    return data
```

---

## 🔒 Forensic Non-Repudiation

By combining the **Trust Hierarchy** with **State Isolation**, AgentV ensures that the final `run.jsonl` trace is an accurate reflection of the agent's decisions, unpolluted by side-effects from the evaluation infrastructure itself. This satisfies the requirements for **NIST AI-100-1** and **GDPR Audit Trails**.
