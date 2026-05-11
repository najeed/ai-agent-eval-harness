---
title: Agent Interaction Contract
description: Reference for the API contract between the harness and the AI agent under test.
---

This document describes the expected API contract between the AgentV harness and the AI agent.

## 📡 Primary Endpoint
By default, the harness expects the agent to expose a REST endpoint:
```text
POST /execute_task
```

### Request Payload
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `task_description`| string | ✅ | The current instruction for the agent. |
| `turn` | integer| ✅ | Current turn number (1 to `MAX_TURNS`). |
| `conversation_history`| array | ❌ | History of previous turns. |
| `identity_binding`| object | ❌ | Cryptographic proof of agent identity. |
| `span_context` | object | ❌ | Distributed tracing metadata (OTel 1.40.0). |
| `run_id` | string | ✅ | Mandatory Run ID for forensic vault affinity. |

---

## 🛠️ Response Protocol
The agent must return an **Action Object** indicating its next step.

### Hub Actions
- **`call_tool`**: Execute a single sandboxed tool.
- **`call_multiple_tools`**: Execute a bundle of tool calls (parallel execution).
- **`final_answer`**: Terminates the session with a summary of accomplishment.
- **`hitl_pause`**: Pause evaluation for human-in-the-loop intervention.

### Example: Multi-Tool Call (Parameterized)
```json
{
  "action": "call_multiple_tools",
  "tool_calls": [
    {
      "tool": "run_line_test",
      "params": {"port": 8080}
    },
    {
      "tool": "check_firmware",
      "params": {"version": "1.4.0"}
    }
  ],
  "summary": "Performing remote diagnostics with specific parameters."
}
```
:::note
In AES v1.6.0+, `call_multiple_tools` supports the `tool_calls` array for parameterized parallel execution. The legacy `tool_names` (string array) format is still supported for no-op parameter calls.
:::

---

## 📡 Receiving Tool Outputs

After an agent issues a `call_tool` or `call_multiple_tools` action, the **harness executes the tools** and returns the results to the agent in the subsequent turn's `conversation_history`. 

:::important
**Logical Direction**: The agent never returns `tool_outputs` in its own response. It only requests tool execution. The harness is the sole authoritative source of environment data and tool results.
:::

---

## 🧬 Behavioral DNA (V1)
 
To ensure that an evaluation trace genuinely reflects the intended scenario logic, AgentV enforces the **Forensic Evidence Ledger**. This provides a verifiable baseline for the environment state (IDs, API keys, and simulator configurations).
 
| Marker | Description |
| :--- | :--- |
| **`topology_hash`** | SHA-256 hash of the `scenario.workflow` structure. |
| **`tool_dna_hash`** | Hash of the tool definitions available to the agent. |
| **`fingerprint_v1`** | A cryptographic digest ensuring the behavioral baseline was not tampered with. |
 
---

## 📡 Forensic Environmental DNA

v1.6.0 elevates the environment to a **First-Class Member** of the evaluation trace.

### Capability-Based Routing
To ensure infrastructure abstraction, scenarios should list **required capabilities** instead of hardcoded endpoints. The Core resolves these via the [Routing Manifest](/spec/routing_v1/).

### Provisioning Snapshots
Every `run.jsonl` trace includes:
1.  **`environmental_snapshot`**: A point-in-time capture of the final merged registry state.
2.  **`provisioning_hash`**: A cryptographic link ensuring the environment hasn't drifted from the sanctioned baseline.

### Event Hierarchy
| Marker | Level | Purpose | Example |
| :--- | :--- | :--- | :--- |
| `PHASE` | Strategic | High-level mission segments. | "Reconstruction", "Targeting" |
| `SUBTASK`| Tactical | Discrete logical missions within a phase. | "Resolve Account", "Verify Sig" |
| `ACTION` | Operational | Individual decisions or tool invocations. | "Call API", "Parse JSON" |
| `STEP` | Atomic | Granular execution units. | "Init Socket", "Buffer Read" |

### Implementation Pattern (JSON Metadata)
Agents should include these markers in their response metadata or specific telemetry headers:

```json
{
  "action": "call_tool",
  "tool_name": "resolve_identity",
  "metadata": {
    "telemetry": {
      "phase": "Public Trust Verification",
      "subtask": "Identity Resolution",
      "action": "GET /v1/identity/system_id/public_key",
      "depth": 2
    }
  }
}
```

---

## 💻 Alternative Protocols

### Local Subprocess (`local://`)
Harness communicates via **Standard I/O**.
- **Request**: Single-line JSON to agent `stdin`.
- **Response**: Single-line JSON from agent `stdout`.
- **Logs**: Captured from `stderr`.

### Persistent Socket (`socket://`)
Harness connects via TCP or Unix sockets. Payloads are newline-delimited JSON strings. This is recommended for high-performance, low-latency integrations.

---

## 🔐 Identity Discovery
The harness automatically discovers the agent's identity and scenario ID with the following priority (Strict AES v1.4+):
1.  **Scenario Metadata (Authoritative)**: `metadata.id` and `metadata.name`.
2.  **Scenario Root**: Top-level `id` or `run_id`.
3.  **Dynamic Discovery**: `metadata.model` or `metadata.agent_name`.
4.  **CLI Overrides**: The `--agent-name` CLI flag or endpoint URL.

:::caution
**Forensic Stability**: In AES v1.4+, the `metadata.id` is the primary key for all audit-grade visualizations. Failing to provide a unique `id` will result in "SILVER" tier compliance warnings.
:::
