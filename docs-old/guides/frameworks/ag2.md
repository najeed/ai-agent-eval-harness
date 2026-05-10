# Quickstart: AG2 + AgentV

Evaluate your AG2 agent workflows using standardized benchmarks.

## 1. Setup Your Agent API
Expose your AG2 agent via a simple `FASTAPI` endpoint.

```python
import ag2
from fastapi import FastAPI

# ... setup your AG2 config ...

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # assistant = autogen.AssistantAgent(...)
    # user_proxy = autogen.UserProxyAgent(...)
    # user_proxy.initiate_chat(assistant, message=request["input"])
    # result = user_proxy.last_message()["content"]
    return {"content": result}
```

## 2. Register Your Agent
```bash
agentv evaluate --run-id <id> --agent http://localhost:8000/execute_task --agent-name "AG2-Dev-Agent"
```

## 3. Generate Verified Report
```bash
agentv report --run-id <id> --share
```
