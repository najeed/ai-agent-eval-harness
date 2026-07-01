# Shim Specification Masterclass: Namespace-Based Resource Mapping

This guide provides an exhaustive inventory of the **AgentV Shim Registry Specification** (v1.0.0). It details how environmental secrets, keys, and resource pointers are injected into the evaluation context.

---

## 🏗️ The Namespace Philosophy

In AgentV, environmental resources are organized into **Namespaces**. This ensures that agents and tools can resolve capabilities without naming collisions.
1.  **Isolation**: Resources are scoped to specific domains (e.g., `git`, `api`, `aws`).
2.  **Portability**: Changing a shim in `shims.d/` updates the agent's environment without requiring code changes to the agent itself.
3.  **Auditor Transparency**: Forensic auditors can inspect shim files to see exactly what environmental access was granted.

---

## Lesson 1: Registry Structure

Shims are resolved via registries located in `.aes/config/shims.d/`. Each file conforms to `spec/shims/shims.schema.json`.

### 1. The `shims` Root
Every registry MUST begin with a `shims` root object.

### 2. Namespace Blocks
Inside the root, each key represents a **Namespace** (e.g., `git`, `telecom`, `internal_api`).
- **`resources`**: Every namespace MUST contain a `resources` block. This is the key-value store for the actual shims.

---

## Lesson 2: Resource Types

Resources can be any valid JSON type, allowing for deep configuration:
- **Strings**: API keys, tokens, or URL base paths.
- **Objects**: Complex configurations (e.g., auth headers or database connection strings).
- **Arrays**: Lists of permitted endpoints or resource IDs.

---

## Lesson 3: The Trust Mechanism (v1.6.0)

To maintain security during evaluation, shims are assigned a **Trust Level** via the optional `trusted` property in the namespace block.

| Property | Type | Default | Purpose |
| :--- | :--- | :--- | :--- |
| **`trusted`** | Boolean | `false` | If `true`, any metrics registered by this shim's code receive **System Context** access. |

### Why Trust Matters
When a shim registers a custom evaluation metric (via the `on_register_simulators` or through the `MetricRegistry`), the engine must decide what data that metric can see. 
- **Trusted Shims**: Can see global `session_metadata` and infrastructure telemetry.
- **Untrusted Shims**: Are restricted to the "Standard" context (Redacted) to prevent exfiltration of sensitive session data.

> [!TIP]
> **Performance Optimization**: Like plugins, untrusted shims incur a deep-copy cost for mutable context (history/state). Mark internal enterprise shims as `trusted` to enable direct zero-copy access for high-frequency metrics.

---

## Reference Walkthrough: Multi-Namespace Shim

```json
{
  "shims": {
    "api": {
      "trusted": true,
      "resources": {
        "api_key": "sk-industrial-001",
        "endpoint": "https://api.vault.internal/v1"
      }
    },
    "git": {
      "trusted": false,
      "resources": {
        "auth": {
          "token": "ghp_1234567890",
          "provider": "enterprise-github"
        }
      }
    }
  }
}
```
