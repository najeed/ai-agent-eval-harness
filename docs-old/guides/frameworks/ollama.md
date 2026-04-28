# Quickstart: Ollama + AgentV

Test your local agent workflows powered by Ollama.

## 1. Setup Your Agent API
standardize your local Ollama calls.

```python
import requests
from fastapi import FastAPI

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama4", "prompt": request["task_description"], "stream": False}
    )
    return {"content": response.json()["response"]}
```

## 2. Register Your Model
```bash
agentv evaluate --run-id <id> --agent http://localhost:8000/execute_task --agent-name "Ollama-Llama4-Local"
```

## 3. Generate Verified Report
```bash
agentv report --run-id <id> --share
```
