---
title: Anthropic Claude
description: Integration guide for Anthropic Claude agents and models.
---

# Anthropic Claude Integration (August 2026)

AgentV provides first-class support for the Anthropic Claude ecosystem, including the latest **Claude Opus 5** models.

## 🚀 Native Protocol
Use the `claude` protocol to connect directly to the Anthropic API.

```bash
agentv run --path scenarios/loan_scenario.json --protocol claude --agent claude://claude-opus-5
```

### Configuration
Ensure your `ANTHROPIC_API_KEY` is set in your `.env` file.

```ini
ANTHROPIC_API_KEY=sk-ant-xxx
```

## 🛠 Model Support
As of August 2026, the following models are prioritized in the industrial baseline:
- `claude-opus-5` (Standard Frontier)


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
