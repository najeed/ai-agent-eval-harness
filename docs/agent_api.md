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

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint URL |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
