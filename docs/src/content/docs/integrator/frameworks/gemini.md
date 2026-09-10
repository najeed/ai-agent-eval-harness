---
title: Google Gemini Integration Guide
description: Direct API integration, google-genai SDK support, and resilient evaluation workflows for Gemini models.
---

AgentV provides native support for the Google Gemini model family (including Gemini 2.5 Flash, Gemini 2.5 Pro, and Gemini 3.0 models) via both the direct `google-genai` SDK and the `langchain-google-genai` integration wrapper.

---

## 📦 1. Installation & Extras

To enable Gemini support, install the dedicated provider extra:

```bash
# Direct Google GenAI SDK support:
pip install -e ".[provider-gemini]"

# Or with LangChain Google GenAI wrapper:
pip install -e ".[langchain-gemini]"
```

---

## 🔑 2. Environment Configuration

Set your Gemini or Google AI API key in your `.env` file or environment variables:

```ini
GEMINI_API_KEY=AIzaSy...
# Or:
GOOGLE_API_KEY=AIzaSy...
```

Optional endpoint configuration:
```ini
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1/models
```

---

## 🚀 3. Direct Evaluation via Gemini Protocol Adapter

Evaluate Gemini frontier models directly against AgentV benchmarks using the built-in `gemini` protocol adapter:

```bash
# Evaluate Gemini 3.7 Flash on financial scenarios
agentv evaluate \
  --path industries/finance/scenarios/ \
  --protocol gemini \
  --agent "gemini://gemini-3.7-flash" \
  --agent-name "Gemini-3.7-Flash-Baseline" \
  --attempts 3

# Run single scenario with Gemini 3.7 Pro
agentv run \
  --scenario industries/telecom/scenarios/13814_home_internet_slow_speed.json \
  --protocol gemini \
  --agent "gemini://gemini-3.1-pro"
```

---

## 🛡️ 4. Centralized Resilience & Quota Management

AgentV integrates an automated resilience harness (`eval_runner.llm_resilience`) for all Gemini requests:
- **Typed Error Classification**: Translates upstream Google API exceptions into domain errors (`LLMQuotaExceededError`, `LLMRateLimitError`, `LLMAuthenticationError`, `LLMTransientError`).
- **Full-Jitter Exponential Backoff**: Automatically retries 429 quota exhaustion and 503 unavailable errors with decorrelated jitter (`AGENTV_LLM_MAX_RETRIES=3`, `AGENTV_LLM_INITIAL_DELAY=1.0`).
- **Function Calling Stability**: Automatically formats Gemini tool declarations and strips extraneous empty fields to avoid invalid argument schema errors.

---

## 🏗️ 5. Custom Gemini Agent Server (Tool-Use Loop)

If you are evaluating a custom Gemini agent server over HTTP, you can implement the standard AgentV contract:

```python
import os
from fastapi import FastAPI, Request
from google import genai
from google.genai import types

app = FastAPI(title="Gemini Agent Server")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


@app.post("/execute_task")
async def execute_task(request: Request):
    payload = await request.json()
    task_desc = payload["task_description"]
    history = payload.get("conversation_history", [])

    # Format prompt and call Gemini model
    contents = [msg["content"] for msg in history if "content" in msg]
    contents.append(task_desc)

    response = client.models.generate_content(
        model="gemini-3.7-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.0,
        ),
    )

    return {"content": response.text, "status": "completed"}
```

Alternatively, if using LangChain:

```python
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-3.7-flash",
    temperature=0.0,
    google_api_key=os.environ.get("GEMINI_API_KEY"),
)
response = llm.invoke("Resolve the customer issue according to policy.")
```
