---
title: OpenAPI REST Adapter
description: Using the industrial-agnostic adapter to evaluate any REST-based AI agent.
---

# The OpenAPI Adapter

While AgentV provides deep integrations for frameworks like LangGraph and CrewAI, many industrial agents communicate via standardized REST interfaces. The **OpenAPI Adapter** allows you to evaluate any agent that exposes an OpenAPI (Swagger) specification, regardless of its underlying technology stack.

## Protocol Support

The adapter implements two primary industrial communication patterns:

1.  **Synchronous (200 OK)**: For fast-responding agents that provide an immediate decision.
2.  **Asynchronous (202 Accepted + Polling)**: For complex agents that require time to reason. The adapter automatically follows the `Location` header or `status_url` to poll for the final result.

---

## Normalization Hub

heterogeneous agents use different names for their status fields (e.g., `status`, `state`, `result`). The **Dual Normalization Hub** uses lexical heuristics to map these to deterministic Harness actions:

- **`hitl_pause`**: Triggered by keywords like `pending`, `review`, or `waiting`.
- **`final_answer`**: Triggered by keywords like `completed`, `success`, or `approved`.
- **`error`**: Triggered by HTTP 4xx/5xx or keywords like `failure` or `crash`.

### Break-Glass Overrides

For agents with unconventional schemas, you can define custom status mappings directly in your Routing Registry or Scenario metadata:

```json
{
  "overrides": {
    "LOAN_PENDING": "hitl_pause",
    "VERIFICATION_FAILED": "error"
  }
}
```

---

## Execution Guide

### 1. Target the Endpoint
Specify the `openapi://` scheme in your evaluation command or scenario definition.

```bash
agentv evaluate --path openapi://http://localhost:8080/api/v1/agent
```

### 2. OAS Discovery (Handshake)
Upon execution, the adapter performs an automatic handshake. It attempts to fetch `openapi.json` from the endpoint to verify the contract before transmitting the task payload.

### 3. Forensic Trace
Every REST interaction is captured in the **Behavioral DNA** trace. You can inspect the raw JSON requests and responses using the [Integrated Console](/integrator/api-reference/).

:::tip
**Industrial Standard**: When evaluating third-party REST agents, always use a **Zero-Temperature** setting for the LLM judge to ensure that the normalization logic remains stable across multiple runs.
:::
