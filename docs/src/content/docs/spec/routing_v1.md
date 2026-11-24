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
  "aes_version": 1.4,
  "metadata": {
    "id": "loan_approval_01",
    "name": "Loan approval routing",
    "compliance_level": "Standard",
    "capabilities": ["fintech_api"]
  },
  "workflow": {"nodes": [{"id": "assess", "task_description": "Assess the loan"}], "edges": []},
  "evaluation": {}
}
```

# 3. Resolution Logic
The Core (Harness) resolves capabilities using a tiered strategy:
1. **CLI Override**: `--agent` arguments always win.
2. **Exact Match**: The first capability in the scenario's list that matches an entry in `routing.json`.
3. **Default**: The `default` entry in the routing manifest.
4. **Harness Default**: Global `AGENT_API_URL` environment variables.

# 4. Routing Manifest
The manifest is stored in `.aes/config/routing/manifest.json`. See [Routing JSON Schema](/spec/routing/routing.schema.json).

## Example:
```json
{
  "mappings": {
    "fintech_api": {
      "protocol": "sse",
      "endpoint": "http://localhost:8000/stream"
    },
    "default": {
      "protocol": "http",
      "endpoint": "http://chat-model:5000"
    }
  }
}
```
