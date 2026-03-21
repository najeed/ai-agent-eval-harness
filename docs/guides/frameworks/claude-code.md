# Quickstart: Claude Code + MultiAgentEval

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
        model="claude-3-5-sonnet-20240620",
        max_tokens=1024,
        messages=[{"role": "user", "content": request["input"]}]
    )
    return {"content": message.content[0].text}
```

## 2. Register Your Agent
```bash
eval-harness evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "Claude-Sonnet-Chef"
```

## 3. Generate Verified Report
```bash
eval-harness report --path runs/run.jsonl --share
```
