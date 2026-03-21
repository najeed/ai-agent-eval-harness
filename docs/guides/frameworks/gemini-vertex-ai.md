# Quickstart: Gemini Vertex AI + MultiAgentEval

Evaluate your enterprise Gemini models on Google Cloud Vertex AI.

## 1. Setup Your Agent API
Wrap your Vertex AI interaction in a standard endpoint.

```python
from vertexai.generative_models import GenerativeModel
from fastapi import FastAPI

model = GenerativeModel("gemini-1.5-pro-002")
app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    response = model.generate_content(request["input"])
    return {"content": response.text}
```

## 2. Register Your Enterprise Agent
```bash
multiagent-eval evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "VertexAI-Gemini-Pro"
```

## 3. Generate Verified Report
```bash
multiagent-eval report --path runs/run.jsonl --share
```
