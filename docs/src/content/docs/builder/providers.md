---
title: LLM & Ecosystem Providers
description: Configuration for Anthropic, Gemini, Grok, Ollama, OpenAI, and other ecosystem adapters.
---

AgentV uses **Ecosystem Adapters** to transparently map evaluation tasks to specific LLM providers. All provider configurations are managed via environment variables to ensure secure, zero-touch deployment.

## ⚙️ Environment Configuration

Set the following variables in your `.env` file or CI/CD secrets to enable provider connectivity.

| Provider | .env Variable | Direct Transport Architecture |
| :--- | :--- | :--- |
| **Anthropic** | `ANTHROPIC_API_KEY`, `CLAUDE_API_URL` | Direct `aiohttp` REST (`/v1/messages`) |
| **Google** | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | Official `google-genai` SDK (`pip install -e ".[provider-gemini]"`) |
| **OpenAI** | `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Direct `aiohttp` REST (`/v1/chat/completions`) |
| **xAI (Grok)** | `GROK_API_KEY`, `GROK_API_URL` | Direct `aiohttp` REST (`/v1/chat/completions`) |
| **Ollama** | `OLLAMA_API_URL` | Direct `aiohttp` REST (`http://localhost:11434/api/chat`) |

:::note
**Zero-SDK Transports**: AgentV communicates directly with Anthropic, OpenAI, Grok, and Ollama via high-performance, asynchronous `aiohttp` HTTP endpoints without heavy third-party vendor SDK dependencies. Only Google Gemini requires `google-genai`, installed via the `provider-gemini` extra. Orchestration frameworks (such as AG2 / AutoGen, CrewAI, and LangGraph) are multi-agent frameworks documented in the [Framework Integration Guide](/builder/frameworks/).
:::

---

## 🔌 Supported Model Adapters

The harness uses custom URI schemes to route tasks to specific providers.

- **`gemini://`**: Uses the official Google GenAI SDK (Default: `gemini-3.7-flash`, `gemini-3.1-pro`).
- **`claude://`**: Direct REST integration with Anthropic Claude models (e.g., `claude-opus-5`, `claude-3.7-sonnet`).
- **`openai://`**: Standard OpenAI v1 REST protocol support (e.g., `gpt-5.6`, `o3`).
- **`grok://`**: Native xAI Grok API integration.
- **`ollama://`**: For local model execution (e.g., `deepseek-r1:70b`, `llama-3.3`).

### Usage in Scenarios
Specific models can be targeted in the scenario definition:

```json
{
  "agent_url": "openai://gpt-5.6",
  "temperature": 0.0
}
```

---

## 🛡️ Centralized LLM Resilience Wrapper

All provider invocations are routed through the centralized resilience harness (`eval_runner.llm_resilience`), which wraps provider requests with typed domain error classification and full-jitter exponential backoff:

### Typed Domain Exceptions
- **`LLMRateLimitError`**: Upstream rate limit or concurrency saturation (HTTP 429).
- **`LLMQuotaExceededError`**: Upstream project quota exhaustion (e.g., `RESOURCE_EXHAUSTED`).
- **`LLMAuthenticationError`**: Missing, invalid, or expired API keys (HTTP 401/403).
- **`LLMTransientError`**: Network disruptions, upstream gateway timeouts, or server errors (HTTP 500/502/503/504).
- **`LLMInvalidRequestError`**: Malformed payload, context window overflow, or unsupported parameters (HTTP 400).
- **`LLMModelNotFoundError`**: Unknown model name or unavailable deployment (HTTP 404).

### Full-Jitter Exponential Backoff
When transient or rate-limit errors occur, the resilience harness applies Decorrelated Full Jitter:
$$\text{delay} = \text{random}(0, \min(\text{max\_delay}, \text{initial\_delay} \times 2^{\text{attempt}}))$$

### Configuration Limits
The resilience runner respects the following environment configuration parameters in `eval_runner/config.py`:

| Parameter | Environment Variable | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `LLM_TIMEOUT` | `AGENTV_LLM_TIMEOUT` | `60.0s` | Individual HTTP request timeout budget. |
| `LLM_MAX_RETRIES` | `AGENTV_LLM_MAX_RETRIES` | `3` | Maximum retry attempts for transient/quota errors. |
| `LLM_INITIAL_DELAY`| `AGENTV_LLM_INITIAL_DELAY`| `1.0s` | Base exponential backoff delay. |
| `LLM_MAX_DELAY` | `AGENTV_LLM_MAX_DELAY` | `60.0s` | Maximum ceiling for backoff delays. |

---

## ⚖️ The Judge Layer (`Luna-Judge`)

The `luna_judge_score` metric can be configured to use any registered provider as the evaluation judge.

### `judge_config` Schema
| Field | Default | Description |
| :--- | :--- | :--- |
| `judge_provider` | `gemini` | The model provider (e.g., `openai`, `gemini`, `ollama`). |
| `judge_model` | `gemini-3.7-flash` | Specific model ID. |
| `judge_rubric` | `generic` | The named rubric to use for scoring. |

### Built-in Rubrics
- **`clinical_safety`**: Healthcare-specific HIPAA and safety audit.
- **`fiduciary_accuracy`**: Financial advice and numerical correctness.
- **`policy_adherence`**: Legal boundary enforcement.
- **`generic`**: Standard semantic similarity.
