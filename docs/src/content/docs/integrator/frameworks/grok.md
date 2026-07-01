---
title: xAI Grok
description: Integration guide for xAI Grok adversarial and reasoning models.
---

# xAI Grok Integration (April 2026)

AgentV provides native support for **Grok 4.20** models, known for their adversarial reasoning and multi-agent capabilities.

## 🚀 Native Protocol
Use the `grok` protocol to connect to the xAI API.

```bash
agentv run --path scenarios/loan_scenario.json --protocol grok --agent grok://grok-4.20-multi-agent
```

### Configuration
Ensure your `XAI_API_KEY` is set in your `.env` file.

```ini
XAI_API_KEY=xai-xxx
```

## 🛠 Model Support
As of April 2026, the following models are supported:
- `grok-4.20-multi-agent` (High-Reasoning)
- `grok-4-fast` (Efficiency)
- `grok-3-mini` (Legacy/Small)

## 🏗 Industrial Benchmarking
Grok's multi-agent capabilities make it ideal for **Agent Topology** testing in the AES specification.

```json
{
  "metadata": {
    "agent_topology": {
      "researcher": { "reads": ["*"] },
      "reviewer": { "writes": ["report"] }
    }
  }
}
```

## 🧪 Adversarial Testing
Grok is frequently used as an **Evaluation Judge** for adversarial scenarios where neutrality is critical. Set `JUDGE_PROVIDER=grok` in your environment to use it as the authoritative scorer.
