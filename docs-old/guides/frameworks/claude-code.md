# Quickstart: Claude Code + AgentV

Rigorous evaluation for Claude-powered agents and MCP (Model Context Protocol) servers.

## 1. Setup Your Agent API
Expose your Claude agent via an API.

```python
import anthropic
from fastapi import FastAPI

client = anthropic.Anthropic()
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    message = client.messages.create(
        model="Claude-4.6-Sonnet",
        max_tokens=1024,
        messages=[{"role": "user", "content": request["task_description"]}]
    )
    return {"content": message.content[0].text}
```

## 2. Register Your Agent
```bash
agentv evaluate --run-id <id> --agent http://localhost:8000/execute_task --agent-name "Claude-4.6-Chef"
```

## 3. Generate Verified Report
```bash
agentv report --run-id <id> --share
```
