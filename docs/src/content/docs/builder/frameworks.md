---
title: Framework Integration Guide
description: Connect LangGraph, AutoGen, CrewAI, and other agent frameworks to AgentV.
---

AgentV is framework-agnostic. You can evaluate agents built with any library (LangChain, AutoGen, CrewAI, etc.) using either **Native Adapters** or **Manual API Wrapping**.

## 🔌 Native Ecosystem Adapters

For the highest level of integration, use native adapters. These typically require a [Plugin](/extender/plugins/) and allow the harness to communicate directly with the framework's internal message bus.

### Supported Adapters
- **`langgraph://`**: Official LangGraph v2 Protocol support.
- **`crewai://`**: Support for CrewAI agent swarms.
- **`ag2://`**: Support for AG2 (formerly AutoGen) agents.

**Usage:**
```bash
agentv evaluate --agent langgraph://my_retail_node
```

### ⚙️ Behavioral Configuration Mesh
As of v1.5.0, native adapters can be granularly configured via the **Industrial Confog Mesh** (e.g., `.aes/config/adapters.d/`). This allows you to define behavioral parameters (like Docker usage or custom timeouts) that are mathematically bound to the evaluation environment.

**Example: Disabling Docker for AG2**
Create `.aes/config/adapters.d/ag2_policy.json`:
```json
{
  "adapters": {
    "settings": {
      "frameworks": {
        "ag2": {
          "use_docker": false
        }
      }
    }
  }
}
```

This configuration ensures that all `ag2://` evaluations in this environment default to non-Docker execution unless overridden by an environment variable.

---

## 🛠️ Manual API Wrapping (HTTP/REST)

If a native adapter is not available, you can wrap your agent in a simple REST API that follows the [Agent API Contract](/extender/api-reference/).

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

### 🟠 AG2 Example
```python
import ag2
from fastapi import FastAPI

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Map input to AG2 initiate_chat
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
agentv evaluate \
  --run-id <id> \
  --agent http://localhost:8000/execute_task \
  --agent-name "Retail-Orchestrator-V1"
```

## 📊 Generating Results
After the run completes, generate a [Verified Report](/evaluator/cli/#report) to analyze the results:
```bash
agentv report --run-id <id> --share
```
