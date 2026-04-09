# Quickstart: OpenAI Assistants + MultiAgentEval

Evaluate your OpenAI Assistant configurations using the harness.

## 1. Setup Your Agent API
Wrap your OpenAI Assistant in an API.

```python
from openai import OpenAI
from fastapi import FastAPI

client = OpenAI()
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # thread = client.beta.threads.create()
    # message = client.beta.threads.messages.create(thread_id=thread.id, role="user", content=request["input"])
    # run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id="YOUR_ASSISTANT_ID")
    # ... (wait for run) ...
    # messages = client.beta.threads.messages.list(thread_id=thread.id)
    return {"content": messages.data[0].content[0].text.value}
```

## 2. Register Your Assistant
```bash
multiagent-eval evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "OpenAI-Assistant-V2"
```

## 3. Generate Verified Report
```bash
multiagent-eval report --path runs/run.jsonl --share
```
