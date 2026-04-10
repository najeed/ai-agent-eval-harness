---
title: LangGraph (v2)
description: Connect your LangGraph state machines to the harness for rigorous evaluation.
---

MultiAgentEval provides native support for LangGraph, allowing you to evaluate state-aware agentic graphs and loops.

## 1. Setup Your Agent API

Expose your LangGraph agent via a standard HTTP endpoint.

```python
from langgraph.graph import StateGraph
from fastapi import FastAPI

app = FastAPI()

# ... (your graph definition) ...

@app.post("/execute_task")
async def execute(request: dict):
    # Process turn with state
    state = {"input": request["task_description"]}
    result = graph.invoke(state)
    return {"action": "final_answer", "summary": result["output"]}
```

## 2. Run Evaluation

Use the `langgraph://` protocol to connect the harness to your agent service.

```bash
multiagent-eval evaluate \
  --run-id <id> \
  --protocol langgraph \
  --agent langgraph://localhost:8000/execute_task \
  --agent-name "LangGraph-Fintech-Orchestrator"
```

## 3. Visual DNA Debugging

The `langgraph://` protocol is optimized for the **Visual Debugger**. It captures the internal state transitions between graph nodes and visualizes them as atomic events in the trajectory map.

```bash
# Launch the console to see the graph transitions
multiagent-eval console
```
