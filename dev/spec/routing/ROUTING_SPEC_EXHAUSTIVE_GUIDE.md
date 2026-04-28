# Routing Specification Masterclass: Infrastructure Decoupling
**Specification Version:** 1.5.0

This guide provides an exhaustive inventory of the **AgentV Routing Specification**. It defines how the engine maps abstract scenario requirements (Capabilities) to physical agent endpoints, supporting industrial-grade protocols like **OpenAPI**.

---

## 🏗️ The Decoupling Philosophy

In AgentV, a scenario never knows **where** an agent lives.
-   **Scenario**: "I need an agent with the `telecom_support` capability."
-   **Routing**: "Based on the current manifest, `telecom_support` maps to an `openapi` endpoint at `http://agent-cluster:5001`."

This decoupling allows scenarios to remain portable across local development, enterprise staging, and production clusters.

---

## Lesson 1: The Routing Manifest (Physical Spec)

The primary configuration is the `manifest.json`. It adheres to `spec/routing/routing.schema.json`.

### Property Table
| Property | Type | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `mappings` | Object | `{}` | Root map of Capability Registry Keys. |
| `mappings.<key>.protocol` | Enum | `http` | Communication protocol: `http`, `local`, `socket`, `grpc`, `openapi`. |
| `mappings.<key>.endpoint` | String | N/A | Destination (URL, CLI Command, or Socket Handle). |
| `mappings.<key>.metadata` | Object | `{}` | Optional environment-specific metadata. |
| `metadata.mapping_overrides` | Object | `{}` | Maps custom agent statuses to Harness actions. |
| `priority` | Integer | 0 | Baseline priority for the entire manifest (used in merging). |

---

## Lesson 2: Distributed Routing (`routing.d/`)

For complex environments, AgentV supports cumulative Routing. The engine scans the `.aes/config/routing.d/` folder for additional fragments (`.json` or `.yaml`).

### The Priority Merging Engine
When multiple files define the same capability mapping, the engine resolves the conflict using a two-tier sort:
1.  **Priority (Primary)**: The mapping from the fragment with the **highest** `priority` value wins.
2.  **Filename (Secondary)**: If priorities are identical, the mapping from the file that is **alphabetically last** (e.g., `99-overrides.json`) wins.

---

## Lesson 3: The Industrial REST Bridge (OpenAPI)

The `openapi` protocol (v1.6.0+) introduces specialized logic for interacting with professional, non-native agent services.

### 1. OAS Discovery Handshake
When an `openapi` route is invoked, the adapter attempts to discover the agent's schema by appending `/openapi.json` to the endpoint. This allows for real-time validation of the payload structure.

### 2. Asynchronous Polling (202 Accepted)
High-latency industrial agents often return a `202 Accepted` status with a `Location` header. The AgentV adapter automatically follows this pattern, entering a secure polling loop until the task reaches a terminal state.

### 3. Agnostic Normalization Hub
Every `openapi` response is passed through the **Dual Normalization Hub**, which maps heterogeneous JSON responses to Harness Core actions:
-   **Lexical Heuristics**: Searches for keywords like `hitl`, `review`, or `pending` to trigger a `hitl_pause`.
-   **Break-Glass Overrides**: Using the `mapping_overrides` metadata, you can explicitly map proprietary statuses (e.g., `{"STATUS": "WAIT_FOR_CLEARANCE"}`) to standard actions (e.g., `hitl_pause`).

---

## Lesson 4: The Resolution Lifecycle

The `RoutingRegistry` resolves addresses using this tiered fallback sequence:

1.  **Exact Capability Match**: Checks the scenario's `capabilities` list against the merged mappings.
2.  **Default Fallback**: Looks for a mapping keyed as `default`.
3.  **Global Fallback**: Relies on the global `AGENT_API_URL` environment variable.

---

## Reference Walkthrough: Industrial Loan Agent Routing

**Scenario**: `loan-audit-v5` (Requires `underwriter_node`)

### 1. Global Manifest (`manifest.json`)
```json
{
  "priority": 0,
  "mappings": {
    "default": { "protocol": "http", "endpoint": "http://localhost:5001" }
  }
}
```

### 2. Regulatory Override (`routing.d/20-loan-gateway.json`)
```json
{
  "priority": 20,
  "mappings": {
    "underwriter_node": {
      "protocol": "openapi",
      "endpoint": "https://internal-bank-api.vfs/loan-service",
      "metadata": {
        "mapping_overrides": {
          "WAITING_FOR_ADMIN": "hitl_pause",
          "REJECTED_BY_POLICY": "final_answer"
        }
      }
    }
  }
}
```

### 3. Resolution Result
The engine finds `underwriter_node`, resolves to the **OpenAPI gateway**, and applies the mapping overrides. If the bank API returns `{"status": "WAITING_FOR_ADMIN"}`, the harness immediately pauses for human intervention, even if the bank API doesn't "know" the AgentV protocol.
