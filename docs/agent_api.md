# Agent API Specification

This document describes the expected API contract between the evaluation harness and the AI agent under test.

## Endpoint

```
POST /execute_task
```

## Request Body

| Field | Type | Required | Description |
|---|---|---|--|
| `task_description` | string | ✅ | The task for the agent to perform |
| `turn` | integer | ✅ | Current turn number in the conversation |
| `conversation_history` | array | ❌ | Array of previous turns (`{role, content}`) |

## Response Body

The agent must return a JSON object with an `action` field indicating what it did:

### `"action": "call_tool"` — Single tool call
```json
{
  "action": "call_tool",
  "tool_name": "get_customer_details",
  "tool_params": {"customer_id": "cust_123"},
  "tool_output": { ... },
  "summary": "Identified customer Jane Doe on 100 Mbps plan."
}
```

### `"action": "call_multiple_tools"` — Multiple tool calls
```json
{
  "action": "call_multiple_tools",
  "tool_names": ["run_line_test", "run_remote_speed_test"],
  "tool_outputs": [{ ... }, { ... }],
  "summary": "Remote diagnostics complete."
}
```

### `"action": "final_answer"` — Task complete
```json
{
  "action": "final_answer",
  "summary": "The issue is resolved. Customer Wi-Fi was on a congested channel."
}
```

### `"action": "provide_instructions"` — Instructions to user
```json
{
  "action": "provide_instructions",
  "instructions": "Please connect via Ethernet and run a speed test.",
  "summary": "Guided customer to perform a local speed test."
}
```

### `"action": "hitl_pause"` — Request Human Intervention
Tells the harness to pause execution and wait for human input. The harness will emit a `HITL_PAUSE` event.
```json
{
  "action": "hitl_pause",
  "reason": "Requesting manual credit override beyond $500 limit."
}
```

### `"action": "branch"` — Fork Trajectory
Signals the `SessionManager` to create a checkpoint and explore a new path.
```json
{
  "action": "branch",
  "metadata": {"reason": "Testing alternative resolution path A"}
}
```

## Multi-turn Flow

The harness supports multi-turn conversations. When the agent returns a `call_tool` or `call_multiple_tools` action, the harness executes the tool(s) via the **Tool Sandbox** and sends the result back as the next `task_description`:

```
Turn 1: Harness → Agent: "Identify the customer..."
         Agent → Harness: {"action": "call_tool", "tool_name": "get_customer_details", ...}
Turn 2: Harness → Agent: "Tool 'get_customer_details' returned: {...}. Continue."
         Agent → Harness: {"action": "final_answer", "summary": "Customer identified."}
```

The loop ends when the agent sends `final_answer`, `provide_instructions`, `error`, or the max turn limit (default: 5) is reached.

### Policy Violations (Governance feedback)

If the agent attempts to call a tool in a way that violates a governance policy (e.g., exceeding a refund limit), the harness will return a `"status": "policy_violation"` in the environment message, allowing the agent to self-correct:

```
Turn 1: Harness → Agent: "Process a $100 refund..."
         Agent → Harness: {"action": "call_tool", "tool_name": "apply_refund", "tool_params": {"amount": 100}}
Turn 2: Harness → Agent: "GOVERNANCE ERROR: Amount 100 exceeds maximum allowed limit of 50. Please adjust."
         Agent → Harness: {"action": "call_tool", "tool_name": "apply_refund", "tool_params": {"amount": 50}}
```

| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |

---

## 💻 Local Subprocess Protocol

When using `--protocol local`, the harness communicates via **Standard I/O**.

1.  **Request**: Harness writes a single-line JSON payload to the agent's `stdin`.
2.  **Response**: Agent must write a single-line JSON response to `stdout`.
3.  **Logs**: Anything the agent writes to `stderr` is captured and emitted as an engine log.

### Example Agent (Python)
```python
import sys, json
for line in sys.stdin:
    payload = json.loads(line)
    # Process...
    print(json.dumps({"action": "final_answer", "summary": "Done"}))
    sys.stdout.flush()
```

## 🔌 Socket Protocol

When using `--protocol socket`, the harness opens a persistent connection:
-   **TCP**: `host:port`
-   **Unix**: `/path/to/socket`

Payloads are exchanged as JSON strings followed by a newline `\n`.

---

## 🔗 Ecosystem Hub Payloads
When using Ecosystem Adapters (`openai://`, `gemini://`, `claude://`), the harness transparently maps the AES scenario into specific provider payloads. The return object follows the same `action` structure as the standard POST request.

### Example: Gemini Adapter Payload
```json
{
  "task": "Process user request...",
  "messages": [{"role": "user", "content": "..."}],
  "model": "gemini-1.5-pro",
  "temperature": 0.7
}
```

### Example: Claude Adapter Payload
```json
{
  "task": "Process user request...",
  "messages": [{"role": "user", "content": "..."}],
  "model": "claude-3-5-sonnet-20240620",
  "system_prompt": "You are a helpful assistant..."
}
```

## Admin Console Integration
The **Admin Console** (`eval-harness console`) utilizes this REST API as its backbone. Enterprise plugins can extend this contract via the `on_register_console_routes` hook to inject custom monitoring or debugging endpoints into the React Native dashboard.

