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


## Agent Identity (Name Discovery)

The harness supports **Zero-Touch Identity Discovery**. Agents can optionally identify themselves by including a `name` or `agent_name` field in their response. This is highly recommended for leaderboards and visual reporting.

The harness discovers the name using the following priority:
1.  **Top-level fields**: `name` or `agent_name`.
2.  **Nested Metadata**: `metadata.name` or `metadata.agent_name`.
3.  **Model Identity**: `metadata.model` (commonly used by LLM-direct adapters).

If no name is discovered, the harness falls back to the manual `--agent-name` CLI flag or the endpoint URL.

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

```

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

Payloads are exchanged as JSON strings followed by a newline `\n`. The harness ensures persistent connection stability during multi-attempt evaluations.

---

---

## 🏛 Benchmark URIs (Community Integration)
The harness natively supports evaluating against major research benchmarks using custom URI schemes:

- **`gaia://[split]`**: Loads scenarios from the GAIA dataset (e.g., `gaia://2023_all`).
- **`assistantbench://[split]`**: Loads scenarios from AssistantBench (e.g., `assistantbench://test`).

These URIs are handled by the `loader.py` which transparently wraps the external data into the standardized AES format with multi-turn metric support.

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

### Example: Grok Adapter Payload
```json
{
  "task": "Process user request...",
  "model": "grok-beta",
  "temperature": 0.0
}
```

### Example: AutoGen Adapter Payload
```json
{
  "task_description": "...",
  "url": "http://localhost:5002/execute_task",
  "conversation_history": [...]
}
```

## Scenario-Level Judge Configuration
The `luna_judge_score` metric can be customized per-scenario or per-criterion using the `judge_config` object. This allows for granular control over the evaluation model and scoring rubrics.

### `judge_config` Schema
| Field | Type | Default | Description |
|---|---|---|---|
| `judge_provider` | string | `.env` default | Model provider (e.g., `openai`, `gemini`, `ollama`) |
| `judge_model` | string | `.env` default | Specific model ID (e.g., `gpt-4.1`, `claude-3-sonnet`) |
| `judge_temperature` | float | `0.0` | Randomness of the judge (higher = less predictable) |
| `judge_rubric` | string | `generic` | The named rubric to use (see below) |

### Built-in Rubrics
The following industry-standard rubrics are available out-of-the-box:
- `clinical_safety`: Healthcare-specific safety and HIPAA compliance check.
- `fiduciary_accuracy`: Financial advice and numerical correctness audit.
- `policy_adherence`: Legal disclosure and boundary enforcement check.
- `factual_grounding`: Evidence-based grounding and hallucination detection.
- `generic`: Standard semantic similarity score.

### Usage Example (Scenario JSON)
```json
{
  "scenario_id": "clinical_trial_summary",
  "criteria": [
    {
      "metric": "luna_judge_score",
      "threshold": 0.9,
      "judge_config": {
        "judge_provider": "openai",
        "judge_model": "gpt-4o",
        "judge_rubric": "clinical_safety"
      }
    }
  ]
}
```

## Admin Console Integration
The **Admin Console** (`eval-harness console`) utilizes this REST API as its backbone. Enterprise plugins can extend this contract via the `on_register_console_routes` hook to inject custom monitoring or debugging endpoints into the React Native dashboard.

