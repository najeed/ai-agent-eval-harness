# Quickstart: OpenAI Assistants + AgentV (April 2026)

Evaluate your OpenAI Assistant configurations using the harness. 

> [!NOTE]
> While AgentV v1.6.0 supports **GPT-5.4 Mini** natively for Chat Completions (via `--protocol openai`), the **Assistants API** (Threads/Runs) still requires a standard HTTP wrapper to bridge the asynchronous execution model.

## 1. Setup Your Agent API
Wrap your OpenAI Assistant in an API to standardize its communication with the harness.

```python
from openai import OpenAI
from fastapi import FastAPI

client = OpenAI()
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Standard Assistant Lifecycle
    thread = client.beta.threads.create()
    client.beta.threads.messages.create(
        thread_id=thread.id, 
        role="user", 
        content=request["task_description"]
    )
    
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id, 
        assistant_id="YOUR_ASSISTANT_ID"
    )
    
    if run.status == 'completed': 
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        return {"content": messages.data[0].content[0].text.value}
    else:
        return {"status": "error", "message": run.status}
```

## 2. Register Your Assistant
```bash
agentv evaluate --run-id <id> --agent http://localhost:8000/execute_task --agent-name "OpenAI-Assistant-V5.4"
```

## 3. Generate Verified Report
```bash
agentv report --run-id <id> --share
```
