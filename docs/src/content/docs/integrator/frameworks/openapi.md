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

Heterogeneous REST agents use varied names and schemas for their status fields (e.g., `status`, `state`, `phase`, `outcome`, `decision`, `result`). The **Dual Normalization Hub** (`eval_runner.adapters.common.DualNormalizationHub`) deterministically maps incoming payloads to canonical AgentV actions using strict precedence:

1. **Transport Failure**: Any HTTP status code $\ge 400$ normalizes to `"error"`.
2. **Explicit Overrides**: Custom overrides defined in the scenario or routing configuration take absolute precedence.
3. **Declared Schema Mapping**: Maps custom fields using declared `status_field` and mapping dictionaries.
4. **Keyword Heuristics**: Analyzes recognized status fields against keyword groups:
   - **`hitl_pause`**: Triggered by keywords like `pending`, `review`, `waiting`, `approval`.
   - **`processing`**: Triggered by keywords like `running`, `in_progress`, `queued` (initiating async polling).
   - **`final_answer`**: Triggered by keywords like `completed`, `success`, `approved`, `done`.
   - **`error`**: Triggered by keywords like `failure`, `crash`, `rejected`.
5. **Content Fallback**: Analyzes payload text content with `normalize_text()`, defaulting to `"final_answer"`.

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

## Preflight Probing & External Telemetry Receipts

### 1. Preflight Health Probing
Before launching multi-turn task evaluations, the OpenAPI adapter verifies endpoint availability and schema contracts:
- Automatically issues a health check probe to `urljoin(endpoint, "/health")` or checks `openapi.json`.
- Fails fast with clear diagnostic logging if the target agent service is unreachable or unauthenticated.

### 2. External Tool Receipts Ingestion
When an OpenAPI service reports internal tool executions via `execution_receipt` or `tool_calls`:
- The adapter forwards the steps directly to the session manager.
- Emits `EXTERNAL_TOOL_CALL` and `EXTERNAL_TOOL_RESULT` events with `source="external_agent_telemetry"` and `provenance="reported"`.
- Binds canonical RFC 8785 SHA3-256 receipt digests (`receipt_hash`) without modifying sandbox-executed tool state.

---

## Execution Guide

### 1. Target the Endpoint
Specify the `--agent` endpoint and `--protocol` in your evaluation command:

```bash
agentv run --path scenarios/loan_scenario.json --protocol http --agent openapi://http://localhost:8080/api/v1/agent
```

### 2. OAS Discovery (Handshake)
Upon execution, the adapter performs an automatic handshake. It attempts to fetch `openapi.json` from the endpoint to verify the contract before transmitting the task payload.

### 3. Forensic Trace
Every REST interaction is captured in the **Behavioral DNA** trace. You can inspect the raw JSON requests and responses using the [Integrated Console](/integrator/api-reference/).

:::tip
**Industrial Standard**: When evaluating third-party REST agents, always use a **Zero-Temperature** setting for the LLM judge to ensure that the normalization logic remains stable across multiple runs.
:::
