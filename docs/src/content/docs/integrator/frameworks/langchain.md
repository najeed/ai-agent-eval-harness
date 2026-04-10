---
title: LangChain
description: Connect your LangChain chains and agents to the evaluation platform.
---

MultiAgentEval provides native support for LangChain, allowing you to evaluate chains, agents, and complex RAG workflows.

## 1. Setup Your Agent API

Expose your LangChain agent via a standard HTTP endpoint or using **LangServe**.

```python
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage
from fastapi import FastAPI

chat = ChatOpenAI()
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Process turn
    result = chat([HumanMessage(content=request["task_description"])])
    return {"action": "final_answer", "summary": result.content}
```

## 2. Run Evaluation

Use the `langchain://` protocol to connect the harness to your agent service.

```bash
multiagent-eval evaluate \
  --run-id <id> \
  --protocol langchain \
  --agent langchain://localhost:8000/execute_task \
  --agent-name "LangChain-Retail-Bot"
```

## 3. Verify Grounding

If your LangChain agent uses RAG, MultiAgentEval can track and visualize **Grounding Coverage** heatmaps to show which parts of your knowledge base were used to answer specific tasks.

```bash
# Reports are generated automatically in:
# reports/coverage/
```
