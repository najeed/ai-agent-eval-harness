# Quickstart: LangChain + MultiAgentEval

Connect your LangChain chains and agents to the evaluation platform.

## 1. Setup Your Agent API
Expose your chain via `LangServe` or a direct API.

```python
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage
from fastapi import FastAPI

chat = ChatOpenAI()
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    result = chat([HumanMessage(content=request["input"])])
    return {"content": result.content}
```

## 2. Register Your Agent
```bash
eval-harness evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "LangChain-Agent-V1"
```

## 3. Generate Verified Report
```bash
eval-harness report --path runs/run.jsonl --share
```
