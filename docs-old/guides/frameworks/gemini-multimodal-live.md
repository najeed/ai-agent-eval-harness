# Quickstart: Gemini Multimodal + AgentV (April 2026)

Evaluate the latest Gemini agents using the harness for multimodal and reasoning benchmarks.

> [!IMPORTANT]
> AgentV has migrated to the **google-genai v1.70.0** SDK. While the core `gemini` adapter is multimodal-ready, current payload mapping focuses on high-fidelity text-based reasoning with **Gemini 2.5 Flash**.

## 1. Setup Your Agent API
Expose your Gemini agent via an API that standardizes the input and output for multimodal tasks.

```python
from google import genai
from fastapi import FastAPI

client = genai.Client(api_key="YOUR_API_KEY")
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Standardize the prompt for Gemini 2.5
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=request["task_description"]
    )
    return {"content": response.text}
```

## 2. Register the Agent
```bash
agentv evaluate --run-id <id> --agent http://localhost:8000/execute_task --agent-name "Gemini-2.5-Pro-Live"
```

## 3. Generate Verified Report
```bash
agentv report --run-id <id> --share
```
