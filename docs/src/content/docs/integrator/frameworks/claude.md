---
title: Anthropic Claude Integration Guide
description: Direct API integration and evaluation workflows for Anthropic Claude 3.7 Sonnet and Claude Opus 5.
---

AgentV provides first-class support for the Anthropic Claude model family, including **Claude Opus 5** and **Claude 3.7 Sonnet**.

---

## 🔑 1. Environment Configuration

Set your Anthropic API key in your `.env` file or environment variables:

```ini
ANTHROPIC_API_KEY=sk-ant-api03-...
```

---

## 🚀 2. Direct Evaluation via Claude Protocol Adapter

Evaluate Claude frontier models directly against AgentV benchmarks using the built-in `claude` protocol adapter without needing an intermediary web service:

```bash
# Evaluate Claude Opus 5 on financial scenarios
agentv evaluate \
  --path industries/finance/scenarios/ \
  --protocol claude \
  --agent "claude://claude-opus-5" \
  --agent-name "Claude-Opus-5-Baseline" \
  --attempts 3

# Evaluate Claude 3.7 Sonnet on GAIA benchmarks
agentv run \
  --scenario gaia://level1 \
  --protocol claude \
  --agent "claude://claude-3-7-sonnet-20250219"
```

---

## 🏗️ 3. Custom Claude Agent Server (Tool-Use Loop)

If you are evaluating a custom Claude agent service with multi-turn tool calling:

```python
import os
from fastapi import FastAPI, Request
from anthropic import Anthropic

app = FastAPI(title="Claude 3.7 Agent Server")
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


@app.post("/execute_task")
async def execute_task(request: Request):
    payload = await request.json()
    task_desc = payload["task_description"]
    history = payload.get("conversation_history", [])
    available_tools = payload.get("available_tools", [])

    # Map available tools to Anthropic tool schemas
    tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in available_tools
    ]

    # Convert conversation history
    messages = []
    for msg in history:
        role = "assistant" if msg["role"] == "assistant" else "user"
        content = msg.get("content") or msg.get("summary", "")
        messages.append({"role": role, "content": content})

    if not messages:
        messages.append({"role": "user", "content": task_desc})

    # Call Claude API
    response = client.messages.create(
        model="claude-3-7-sonnet-20250219",
        max_tokens=4096,
        tools=tools if tools else None,
        messages=messages,
    )

    # Check for tool use requests
    for block in response.content:
        if block.type == "tool_use":
            return {
                "action": "call_tool",
                "tool_name": block.name,
                "tool_args": block.input,
                "summary": f"Requesting tool: {block.name}",
            }

    # Extract final text answer
    text_content = "".join([b.text for b in response.content if b.type == "text"])
    return {"action": "final_answer", "summary": text_content}
```
