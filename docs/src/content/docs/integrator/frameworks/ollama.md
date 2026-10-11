---
title: Ollama (Local)
description: Integration guide for local model execution via Ollama.
---

# Ollama Local Integration (April 2026)

AgentV supports local model evaluation via Ollama, enabling private, high-speed benchmarking for open-source models like **Llama 4**.

## 🚀 Native Protocol
Use the `ollama` protocol to connect to a local Ollama instance.

```bash
agentv run --path scenarios/loan_scenario.json --protocol ollama --agent ollama://llama4
```

### Configuration
By default, the harness attempts to connect to `http://localhost:11434`. You can override this in your `.env`:

```ini
OLLAMA_HOST=http://your-server:11434
OLLAMA_MODEL=llama4
```

## 🛠 Supported Models
AgentV is optimized for the 2026 local model landscape:
- `llama4` (8B, 70B, 400B)
- `mistral-v4`
- `phi-5`

## 🧪 Benchmarking Local vs. Cloud
A common research use case is comparing a local model against a cloud baseline (e.g., Llama 4 vs. GPT-5.6). 

Run the evaluations with distinct run IDs and generate a comparative leaderboard:
```bash
# 1. Run local model
agentv run --scenario scenarios/loan_scenario.json --protocol ollama --agent ollama://llama4 --run-id run_llama4

# 2. Run cloud baseline
agentv run --scenario scenarios/loan_scenario.json --protocol openai --agent openai://gpt-5.6 --run-id run_gpt56

# 3. Generate comparative ranking
agentv leaderboard --dir runs/ --output LEADERBOARD.md
```

## ⚠️ Performance Note
Local execution speed depends on your hardware (GPU/RAM). If you experience timeouts during evaluation, increase the `DEFAULT_ADAPTER_TIMEOUT` in your config.
