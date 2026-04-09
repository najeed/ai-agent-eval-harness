---
title: "Capability-Based Routing v1.0.0"
description: "Specification for infrastructure abstraction and target decoupling"
---

# 1. Overview
Capability-Based Routing decouples the **Intent** of a scenario (what capabilities it needs) from the **Infrastructure** (where those services are hosted).

# 2. The Abstraction Principle
Scenarios SHOULD NOT define hardcoded endpoints. Instead, they define required capabilities:
```json
{
  "scenario_id": "loan_approval_01",
  "capabilities": ["fintech_api"]
}
```

# 3. Resolution Logic
The Core (Harness) resolves capabilities using a tiered strategy:
1. **CLI Override**: `--agent` arguments always win.
2. **Exact Match**: The first capability in the scenario's list that matches an entry in `routing.json`.
3. **Default**: The `default` entry in the routing manifest.
4. **Harness Default**: Global `AGENT_API_URL` environment variables.

# 4. Routing Manifest
The manifest is stored in `.aes/config/routing/manifest.json`. See [Routing JSON Schema](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/spec/routing/routing.schema.json).

## Example:
```json
{
  "mappings": {
    "fintech_api": {
      "protocol": "http",
      "endpoint": "http://localhost:8000"
    },
    "default": {
      "protocol": "http",
      "endpoint": "http://chat-model:5000"
    }
  }
}
```
