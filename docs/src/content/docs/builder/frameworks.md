---
title: Framework Integration Guide
description: Connect LangGraph, AutoGen, CrewAI, and other agent frameworks to MultiAgentEval.
---

MultiAgentEval is framework-agnostic. You can evaluate agents built with any library (LangChain, AutoGen, CrewAI, etc.) using either **Native Adapters** or **Manual API Wrapping**.

## 🔌 Native Ecosystem Adapters

For the highest level of integration, use native adapters. These typically require a [Plugin](/ai-agent-eval-harness/extender/plugins/) and allow the harness to communicate directly with the framework's internal message bus.

### Supported Adapters (2026 Baseline)
- **`langgraph://`**: Official LangGraph v2 Protocol support.
- **`crewai://`**: Support for CrewAI agent swarms.
- **`autogen://`**: Support for Microsoft AutoGen agents.

**Usage:**
```bash
multiagent-eval evaluate --agent langgraph://my_retail_node
```

---

## 🛠️ Manual API Wrapping (HTTP/REST)

If a native adapter is not available, you can wrap your agent in a simple REST API that follows the [Agent API Contract](/ai-agent-eval-harness/extender/api-reference/).

### 🟢 LangGraph Example
```python
from langgraph.graph import StateGraph
from fastapi import FastAPI

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    state = {"input": request["input"]}
    result = graph.invoke(state)
    return {"content": result["output"]}
```

### 🟠 AutoGen Example
```python
import autogen
from fastapi import FastAPI

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Map input to AutoGen initiate_chat
    user_proxy.initiate_chat(assistant, message=request["input"])
    return {"content": user_proxy.last_message()["content"]}
```

### 🔵 CrewAI Example
```python
from crewai import Crew
from fastapi import FastAPI

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    crew = Crew(agents=[...], tasks=[...])
    result = crew.kickoff()
    return {"content": result}
```

---

## 🚀 Registering Your Agent

Once your agent is running (manually or via a native scheme), register it with the evaluation engine:

```bash
multiagent-eval evaluate \
  --run-id <id> \
  --agent http://localhost:8000/execute_task \
  --agent-name "Retail-Orchestrator-V1"
```

## 📊 Generating Results
After the run completes, generate a [Verified Report](/ai-agent-eval-harness/evaluator/reports/) to analyze the results:
```bash
multiagent-eval report --run-id <id> --share
```
