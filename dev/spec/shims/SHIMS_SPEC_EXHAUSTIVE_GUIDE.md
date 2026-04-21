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

## Reference Walkthrough: Multi-Namespace Shim

```json
{
  "shims": {
    "api": {
      "resources": {
        "api_key": "sk-industrial-001",
        "endpoint": "https://api.vault.internal/v1"
      }
    },
    "git": {
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
