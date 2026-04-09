# Quickstart: Gemini Multimodal Live + MultiAgentEval

Evaluate the latest Gemini agents using the harness for multimodal and reasoning benchmarks.

## 1. Setup Your Agent API
Expose your Gemini agent via an API that standardizes the input and output.

```python
import google.generativeai as genai
from fastapi import FastAPI

genai.configure(api_key="YOUR_API_KEY")
model = genai.GenerativeModel("gemini-1.5-pro")

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Standardize the prompt for Gemini
    response = model.generate_content(request["input"])
    return {"content": response.text}
```

## 2. Register the Agent
```bash
multiagent-eval evaluate --path scenarios/ --agent http://localhost:8000/execute_task --agent-name "Gemini-1.5-Pro-Live"
```

## 3. Generate Verified Report
```bash
multiagent-eval report --path runs/run.jsonl --share
```
