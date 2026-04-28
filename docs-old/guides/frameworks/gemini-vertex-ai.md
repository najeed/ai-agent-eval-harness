# Quickstart: Gemini Vertex AI + AgentV (April 2026)

Evaluate your enterprise Gemini models on Google Cloud Vertex AI using either native protocols or standard API wrappers.

## 1. Native Integration (Recommended)
As of v1.6.0, AgentV supports Vertex AI natively through the `gemini` adapter using the `google-genai` SDK.

### Configuration
You can trigger Vertex AI mode by setting `vertexai: true` in your agent metadata or by using a `vertex` hint in the URL.

```bash
agentv evaluate --run-id <id> --protocol gemini --agent gemini://gemini-2.5-pro --metadata '{"vertexai": true}'
```

## 2. Setup via Agent API (Legacy/Custom)
If you prefer to wrap your Vertex AI interaction in a custom endpoint:

```python
from google import genai
from fastapi import FastAPI

client = genai.Client(vertexai=True, project="your-project", location="us-central1")
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=request["input"]
    )
    return {"content": response.text}
```

## 3. Register Your Enterprise Agent
```bash
agentv evaluate --run-id <id> --agent http://localhost:8000/execute_task --agent-name "VertexAI-Gemini-Pro"
```

## 4. Generate Verified Report
```bash
agentv report --run-id <id> --share
```
