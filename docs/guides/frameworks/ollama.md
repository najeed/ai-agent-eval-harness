# Quickstart: Ollama + MultiAgentEval

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
        json={"model": "llama3", "prompt": request["input"], "stream": False}
    )
    return {"content": response.json()["response"]}
```

## 2. Register Your Model
```bash
multiagent-eval evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "Ollama-Llama3-Local"
```

## 3. Generate Verified Report
```bash
multiagent-eval report --path runs/run.jsonl --share
```
