---
title: "Agent Targets Specification"
description: "Authoritative specification for agent target definitions, connection protocols, and authentication schemes."
---

The **Agent Targets Specification** (`agent-targets.schema.json`) defines connection parameters, authentication methods, rate limits, and protocol bindings for target AI models and agent services under evaluation.

---

## 1. Agent Target Schema (`agent-targets.schema.json`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Agent Targets Definition",
  "type": "object",
  "required": ["targets"],
  "properties": {
    "targets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "protocol", "endpoint"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "protocol": {
            "type": "string",
            "enum": ["http", "local", "socket", "langgraph", "crewai", "ag2", "gemini", "claude", "openai", "ollama"]
          },
          "endpoint": { "type": "string" },
          "model": { "type": "string" },
          "auth": {
            "type": "object",
            "properties": {
              "type": { "type": "string", "enum": ["bearer", "api_key", "basic", "none"] },
              "token_env": { "type": "string" },
              "header_name": { "type": "string" }
            }
          },
          "timeout_seconds": { "type": "number", "default": 30 },
          "max_retries": { "type": "integer", "default": 3 }
        }
      }
    }
  }
}
```

---

## 2. Standard 2026 Frontier Target Profiles

| Target ID | Name | Protocol | Endpoint / URI | Auth Token Env |
| :--- | :--- | :--- | :--- | :--- |
| `gemini-3.7-flash` | Google Gemini 3.7 Flash | `gemini` | `gemini://gemini-3.7-flash` | `GEMINI_API_KEY` |
| `claude-opus-5` | Anthropic Claude Opus 5 | `claude` | `claude://claude-opus-5` | `ANTHROPIC_API_KEY` |
| `claude-3.7-sonnet`| Anthropic Claude 3.7 Sonnet | `claude` | `claude://claude-3-7-sonnet-20250219` | `ANTHROPIC_API_KEY` |
| `gpt-5.6` | OpenAI GPT-5.6 | `openai` | `openai://gpt-5.6` | `OPENAI_API_KEY` |
| `deepseek-r1-70b` | Ollama DeepSeek R1 70B | `ollama` | `ollama://deepseek-r1:70b` | None (Local) |
