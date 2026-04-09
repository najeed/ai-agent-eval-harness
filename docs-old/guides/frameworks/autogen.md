# Quickstart: AutoGen + MultiAgentEval

Evaluate your AutoGen agent workflows using standardized benchmarks.

## 1. Setup Your Agent API
Expose your AutoGen agent via a simple `FASTAPI` endpoint.

```python
import autogen
from fastapi import FastAPI

# ... setup your autogen config ...

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
multiagent-eval evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "AutoGen-Dev-Agent"
```

## 3. Generate Verified Report
```bash
multiagent-eval report --path runs/run.jsonl --share
```
