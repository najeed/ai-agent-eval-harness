---
title: Agent Interaction Contract
description: Reference for the API contract between the harness and the AI agent under test.
---

This document describes the expected API contract between the MultiAgentEval harness and the AI agent.

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
| `identity_binding`| object | ❌ | Cryptographic proof of agent identity (Industrial v1.4). |
| `span_context` | object | ❌ | Distributed tracing metadata (OTel 1.40.0). |

---

## 🛠️ Response Protocol
The agent must return an **Action Object** indicating its next step.

### Hub Actions
- **`call_tool`**: Execute a single sandboxed tool.
- **`call_multiple_tools`**: Execute a bundle of tool calls (parallel execution).
- **`final_answer`**: Terminates the session with a summary of accomplishment.
- **`hitl_pause`**: Pause evaluation for human-in-the-loop intervention.
- **`branch`**: Signals the engine to fork the trajectory for alternative exploration.

### Example: Multi-Tool Call
```json
{
  "action": "call_multiple_tools",
  "tool_names": ["run_line_test", "check_firmware"],
  "tool_outputs": [{}, {}],
  "summary": "Performing remote diagnostics."
}
```

---

## 🧬 Industrial Telemetry (Behavioral DNA)
High-stakes agents can optionally emit hierarchical markers to support forensic auditing:
- **`PHASE`**: Macro segments (e.g., "Reasoning").
- **`SUBTASK`**: Discrete logic units.
- **`ACTION`**: Individual tool decisions.

These are captured by the harness's **Behavioral DNA Bus** and reconstructed in real-time on the Visual Console.

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
The harness automatically discovers the agent's identity using the following priority:
1.  **Top-level**: `name` or `agent_name`.
2.  **Metadata**: `metadata.model` or `metadata.agent_name`.
3.  **Fallback**: The `--agent-name` CLI flag or endpoint URL.
