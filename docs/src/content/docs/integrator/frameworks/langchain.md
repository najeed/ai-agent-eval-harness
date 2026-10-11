---
title: LangChain
description: Connect your LangChain chains and agents to the evaluation platform.
---

AgentV provides native support for LangChain, allowing you to evaluate chains, agents, and complex RAG workflows.

## 1. Setup Your Agent API

Expose your LangChain agent via a standard HTTP endpoint or using **LangServe**.

```python
from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

chat = ChatOpenAI(model="gpt-5.6")
app = FastAPI()


@app.post("/execute_task")
async def execute(request: dict):
  # Process turn
  task_desc = request.get("task_description", "")
  result = chat.invoke([HumanMessage(content=task_desc)])
  return {"action": "final_answer", "summary": result.content}
```

## 2. Run Evaluation

Execute the evaluation against your FastAPI service using `--protocol http`:

```bash
agentv run \
  --path scenarios/loan_scenario.json \
  --protocol http \
  --agent http://localhost:8000/execute_task \
  --agent-name "LangChain-Retail-Bot"
```

:::tip
**Native LangServe / In-Process Protocol**: If your chain is hosted with **LangServe** or executed in-process, use `--protocol langchain`:
```bash
# LangServe remote deployment:
agentv run \
  --path scenarios/loan_scenario.json \
  --protocol langchain \
  --agent http://localhost:8000/my_chain

# Or in-process Runnable binding (specifying metadata.chain_path in scenario):
agentv run \
  --path scenarios/loan_scenario.json \
  --protocol langchain
```
:::

## 3. Verify Grounding

If your LangChain agent uses RAG, AgentV can track and visualize **Grounding Coverage** heatmaps to show which parts of your knowledge base were used to answer specific tasks.

```bash
# Reports are generated automatically in:
# reports/coverage/
```
