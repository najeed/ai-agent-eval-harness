---
title: Anthropic Claude
description: Integration guide for Anthropic Claude agents and models.
---

# Anthropic Claude Integration (April 2026)

AgentV provides first-class support for the Anthropic Claude ecosystem, including the latest **Claude 4.6** models.

## 🚀 Native Protocol
Use the `claude` protocol to connect directly to the Anthropic API.

```bash
agentv run --path scenarios/loan_scenario.json --protocol claude --agent claude://claude-4-6-sonnet
```

### Configuration
Ensure your `ANTHROPIC_API_KEY` is set in your `.env` file.

```ini
ANTHROPIC_API_KEY=sk-ant-xxx
```

## 🛠 Model Support
As of April 2026, the following models are prioritized in the industrial baseline:
- `Claude-4.6-Sonnet` (Standard)
- `claude-4-6-opus` (High-Reasoning)
- `claude-4-5-haiku` (Fast)

## 🏗 Framework Integration
If you are using Claude with a framework like **Claude Code** or **LangGraph**, see the respective guides:
- [LangGraph](/integrator/frameworks/langgraph)
- [LangChain](/integrator/frameworks/langchain)

## 🧪 Advanced: Multi-Modal (Vision)
The `claude` adapter supports high-fidelity vision tasks. To benchmark multimodal performance, ensure your agent payload includes standard image components.

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe this image."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}
      ]
    }
  ]
}
```
