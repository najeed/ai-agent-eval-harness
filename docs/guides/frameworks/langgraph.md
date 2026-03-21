# Quickstart: LangGraph + MultiAgentEval

Connect your LangGraph state machines to the harness for rigorous evaluation.

## 1. Setup Your Agent API
Expose your LangGraph agent via a simple `aiohttp` or `FASTAPI` endpoint:

```python
from langgraph.graph import StateGraph
from fastapi import FastAPI

app = FastAPI()
# ... (your graph definition) ...

@app.post("/execute_task")
async def execute(request: dict):
    state = {"input": request["input"]}
    result = graph.invoke(state)
    return {"content": result["output"]}
```

## 2. Register the Agent
```bash
multiagent-eval evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "LangGraph-Retail-V1"
```

## 3. Generate Verified Report
```bash
multiagent-eval report --path runs/run.jsonl --share
```
