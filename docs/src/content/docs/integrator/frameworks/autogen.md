---
title: Microsoft AutoGen
description: Evaluate your AutoGen agent workflows using standardized benchmarks.
---

AgentV provides native support for AutoGen agent workflows, allowing you to measure the performance of complex multi-agent conversations.

## 1. Setup Your Agent API

Expose your AutoGen agent via a standard HTTP endpoint.

```python
from autogen import AssistantAgent, UserProxyAgent
from fastapi import FastAPI

app = FastAPI(title="AutoGen Evaluation Service")

# Setup agent configuration
config_list = [{"model": "gpt-4o", "api_key": "YOUR_API_KEY"}]
assistant = AssistantAgent(
    name="assistant",
    llm_config={"config_list": config_list},
)
user_proxy = UserProxyAgent(
    name="user_proxy",
    code_execution_config=False,
    human_input_mode="NEVER",
)


@app.post("/execute_task")
async def execute(request: dict):
    task_desc = request.get("task_description", "")
    chat_result = user_proxy.initiate_chat(assistant, message=task_desc)
    result = chat_result.summary or user_proxy.last_message()["content"]
    return {"action": "final_answer", "summary": result}
```

## 2. Run Evaluation

Execute the evaluation against your FastAPI agent service using `--protocol http`:

```bash
agentv run \
  --path scenarios/loan_scenario.json \
  --protocol http \
  --agent http://localhost:8000/execute_task \
  --agent-name "AG2-Finance-Expert"
```

:::tip
**Native AG2 Protocol**: To evaluate a native in-process AutoGen agent without an HTTP service, specify `metadata.agent_path: "my_module:assistant"` in your scenario and use `--protocol ag2`:
```bash
agentv run \
  --path scenarios/loan_scenario.json \
  --protocol ag2
```
:::

## 3. Review DNA Trajectories

Launch the console to see the internal transitions between your AutoGen agents visualized in a high-fidelity trajectory map.

```bash
agentv console
```
