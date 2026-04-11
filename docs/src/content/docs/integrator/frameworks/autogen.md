---
title: Microsoft AutoGen
description: Evaluate your AutoGen agent workflows using standardized benchmarks.
---

AgentV provides native support for AutoGen agent workflows, allowing you to measure the performance of complex multi-agent conversations.

## 1. Setup Your Agent API

Expose your AutoGen agent via a standard HTTP endpoint.

```python
import autogen
from fastapi import FastAPI

# ... setup your autogen config ...

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # assistant = autogen.AssistantAgent(...)
    # user_proxy = autogen.UserProxyAgent(...)
    # user_proxy.initiate_chat(assistant, message=request["task_description"])
    # result = user_proxy.last_message()["content"]
    return {"action": "final_answer", "summary": result}
```

## 2. Run Evaluation

Use the `autogen://` protocol to connect the harness to your agent service.

```bash
agentv evaluate \
  --run-id <id> \
  --protocol autogen \
  --agent autogen://localhost:8000/execute_task \
  --agent-name "AutoGen-Finance-Expert"
```

## 3. Review DNA Trajectories

Launch the console to see the internal transitions between your AutoGen agents visualized in a high-fidelity trajectory map.

```bash
agentv console
```
