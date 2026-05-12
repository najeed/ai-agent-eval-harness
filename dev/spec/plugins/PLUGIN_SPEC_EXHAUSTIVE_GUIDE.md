# Plugin Specification Masterclass: Extensions & Provenance

This guide provides an exhaustive inventory of the **AgentV Plugin Specification**. It defines how to extend the harness without modifying the core engine, ensuring forensic integrity and industrial-grade provenance.

---

## 🏗️ The Extension Philosophy: Zero-Touch

AgentV uses a **Zero-Touch Plugins** architecture. This means:
1.  **Isolation**: Plugins live outside the core engine.
2.  **Immutability**: The core engine logic remains signed and untampered.
3.  **Auditability**: Every plugin used in a run is hashed and recorded in the forensic trace.

---

## Lesson 1: The Forensic Registry (Physical Spec)

The physical source of truth for plugin registration is the `.aes/config/plugins/registry.json` file. It must adhere to the `spec/plugins/plugins.schema.json`.

### Property Table
| Property | Type | Mandatory? | Purpose |
| :--- | :--- | :--- | :--- |
| `id` | String | Yes | Unique forensic identifier (e.g., `flight_recorder`). |
| `name` | String | Yes | Human-readable name for reporting. |
| `module` | String | Yes | The Python module to import (e.g., `eval_runner.flight_recorder`). |
| `class` | String | Yes | The authoritative Class name (e.g., `FlightRecorderPlugin`). |
| `enabled` | Boolean | No | Toggle to activate/deactivate the plugin. |
| `trusted` | Boolean | No | If `true`, grants elevated access to sensitive session context (System Parameters). |
| `config` | Object | No | Plugin-specific configuration parameters. |

---

## Lesson 2: The BaseEvalPlugin Interface (Functional Spec)

Every plugin must subclass `BaseEvalPlugin`. The spec defines three types of interactions: **Lifecycle Hooks**, **Event Listeners**, and **Interceptors**.

### 1. Lifecycle Hooks
These are the most stable "anchors" in the plugin interface.

| Method | Timing | Use Case |
| :--- | :--- | :--- |
| `before_evaluation` | T=0 (Pre-flight) | Environmental checks, DB initialization. |
| `after_evaluation` | T_end (Landing) | Reporting, scoring summary. |
| `on_register_commands` | CLI Init | Adding custom shell commands (e.g., `agentv compliance`). |
| `on_discover_adapters` | Engine Init | Registering custom agent framework bridges. |
| `on_register_simulators`| Engine Init | Adding new world shims to the registry. |

### 2. Event-Based Hooks (CoreEvents Bridge)
Through the `EventEmitter`, plugins can listen to almost every internal state transition. The harness automatically maps `CoreEvents` names to `on_<event_name>` methods.

| Hook Name | Triggering Event | Access to Context? |
| :--- | :--- | :---: |
| `on_agent_turn_start` | Turn starts | Yes |
| `on_tool_call` | Tool call initiated | Yes |
| `on_tool_result` | Tool output received | Yes |
| `on_error` | System exception | Yes |

### 3. Interceptors (Mutative Specification)
Interceptors allow plugins to **modify** engine behavior in real-time. This is the "Plumbing" used for redirection and masking.

- **Signature**: `trigger_interceptor(hook_name, context, *args, **kwargs)`
- **Return Requirements**:
    - `False`: Immediately blocks the action (e.g., Security block).
    - `Dict`: Contains mutations (e.g., `{"tool_name": "new_tool", "arguments": { ... }}`).

---

## Lesson 3: Forensic Provenance (The Trust Model)

AgentV tracks the **Origin** of every plugin to establish an audit trail.

| Origin | Trust Level | Description |
| :--- | :--- | :--- |
| **CORE** | 100% | Hardcoded in the `ai-agent-eval-harness` core. |
| **MEMBER** | 90% | Installed as a formal package or registered in `registry.json`. |
| **PROJECT** | 70% | Local code in the project `/plugins/` directory. |
| **EXTERNAL** | 50% | Ad-hoc file paths injected via CLI (e.g., `--plugin path/to/file.py`). |

### Trusted Metrics & Sensitive Context (v1.6.0)
The **Metric Dispatcher** uses this provenance map to enforce security boundaries. Metrics registered by plugins are categorized by their trust level:

| Trust Level | Context Access | Parameters Available |
| :--- | :--- | :--- |
| **Trusted** | **System Context** | `session_metadata`, `forensic_telemetry`, `actual_state`, `history` |
| **Standard** | **Redacted Context** | `summary`, `expected`, `actual`, `turns_taken`, `metadata` |

:::important
**Isolation Enforcement**: To prevent side-effects, mutable objects like `history` and `actual_state` are passed as **Deep Copies** to any non-CORE metric. This ensures that a metric cannot mutate the live sandbox state during evaluation.
:::

:::tip
**Performance Optimization**: Deep-copying large conversation histories can be CPU-intensive. For internal/vetted enterprise metrics, set `"trusted": true` in the registry. This grants the metric direct access to the session data without the isolation overhead, effectively removing the "air-gap" for trusted code.
:::

> **Audit Rule**: Runs with `EXTERNAL` plugins are flagged as "Non-Standard" in the Verification Certificate (VC) unless the plugin file hash matches an enterprise-whitelisted baseline.

### The Enterprise Whitelist (Forensic Baselines)
The "whitelist" is not a static list but a **policy layer** resolved through the cumulative registry.

1.  **Implicit Whitelist**: Any plugin registered in `.aes/config/plugins/registry.json` is automatically considered "Provisioned" and whitelisted.
2.  **Explicit Whitelist**: Centralized forensic baselines are stored as `.json` or `.yaml` files within the `.aes/config/forensics.d/` directory. These files contain `allowed_plugin_hashes` (SHA-256).
3.  **Governance Enforcement**: During Trace Certification, the `TraceVerifier` compares the hash of any `EXTERNAL` plugin against these baselines. If a mismatch is found, the **Verification Certificate (VC)** is marked with `compliance_status: "NON_STANDARD_EXTENSION"`.


---

## Reference Implementation: PII Masking Plugin

This plugin demonstrates the **Interceptor** pattern by redacting sensitive data from tool results before they are written to the trace.

```python
from eval_runner.plugins import BaseEvalPlugin
import re

class PIIMaskingPlugin(BaseEvalPlugin):
    """Refinement of the proposed CompliancePlugin logic."""

    def on_tool_result(self, context, tool_name, result):
        """Redact emails from tool results."""
        if isinstance(result, str):
            sanitized = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[REDACTED_EMAIL]", result)
            return sanitized
        return result

    def on_tool_request(self, context, tool_name, arguments):
        """Redact credentials from arguments."""
        if "api_key" in arguments:
            arguments["api_key"] = "[REDACTED_BY_PLUGIN]"
        return {"arguments": arguments}
```

### Registration Entry (`registry.json`)
```json
{
  "plugins": [
    {
      "id": "pii_masker",
      "name": "Forensic PII Masking Plugin",
      "module": "custom_plugins.masking",
      "class": "PIIMaskingPlugin",
      "enabled": true
    }
  ]
}
```
