---
title: LLM & Ecosystem Providers
description: Configuration for Anthropic, Gemini, Grok, Ollama, OpenAI, and other ecosystem adapters.
---

AgentV uses **Ecosystem Adapters** to transparently map evaluation tasks to specific LLM providers. All provider configurations are managed via environment variables to ensure secure, zero-touch deployment.

## ⚙️ Environment Configuration

Set the following variables in your `.env` file or CI/CD secrets to enable provider connectivity.

| Provider | .env Variable | Default Fallback |
| :--- | :--- | :--- |
| **Anthropic** | `CLAUDE_API_URL` | `https://api.anthropic.com/v1/messages` |
| **Google** | `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1/models` |
| **Ollama** | `OLLAMA_API_URL` | `http://localhost:11434/api/chat` |
| **xAI (Grok)** | `GROK_API_URL` | *(Requires active Grok Adapter)* |
| **AutoGen** | `AG2_API_URL` | `http://localhost:5002/execute_task` |

### API Keys
Most providers also require their respective API keys (e.g., `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`).

---

## 🔌 Supported Model Adapters

The harness uses custom URI schemes to route tasks to specific providers.

- **`gemini://`**: Uses the official `google-genai v1.70.0` SDK. (Default: Gemini 2.5 Flash).
- **`claude://`**: Direct integration with Anthropic Claude 3.5/4 models.
- **`openai://`**: Standard OpenAI v1 protocol support.
- **`grok://`**: Native xAI Grok API integration.
- **`ollama://`**: For local model execution.

### Usage in Scenarios
Specific models can be targeted in the scenario definition:

```json
{
  "agent_url": "gemini://gemini-2.5-flash",
  "temperature": 0.0
}
```

---

## ⚖️ The Judge Layer (`Luna-Judge`)

The `luna_judge_score` metric can be configured to use any registered provider as the evaluation judge.

### `judge_config` Schema
| Field | Default | Description |
| :--- | :--- | :--- |
| `judge_provider` | `gemini` | The model provider (e.g., `openai`, `gemini`, `ollama`). |
| `judge_model` | `gemini-2.5-flash`| Specific model ID. |
| `judge_rubric` | `generic` | The named rubric to use for scoring. |

### Built-in Rubrics
- **`clinical_safety`**: Healthcare-specific HIPAA and safety audit.
- **`fiduciary_accuracy`**: Financial advice and numerical correctness.
- **`policy_adherence`**: Legal boundary enforcement.
- **`generic`**: Standard semantic similarity.

---

## 🛠️ Performance & Timeouts

To prevent hung evaluations, all provider calls are subject to the following global limits:

- **`PROVIDER_TIMEOUT`**: 30.0s (Default).
- **`RETRY_COUNT`**: 3 (Exponential backoff for 429/503 errors).

These can be overridden in `eval_runner/config.py` or via the CLI.
