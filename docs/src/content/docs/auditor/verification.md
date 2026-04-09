---
title: Ecosystem Verification
description: Step-by-step instructions to verify third-party integrations, adapters, and environment health.
---

This guide provides the protocols for verifying that your MultiAgentEval environment is production-ready across all framework adapters and proprietary models.

## 🚦 Prerequisites

### Environment Setup
Ensure the harness is installed in editable mode and all API keys are configured in your `.env` file.
```bash
pip install -e .
```

### Dependency Audit
Use the `doctor` utility to perform a global health check of your dependencies and connection status.
```bash
multiagent-eval doctor
```

---

## 🌎 Framework Verification (Adapters)

Verify that the harness can communicate with external frameworks using the appropriate protocols.

### Microsoft AutoGen
- **Protocol**: `autogen://`
- **Verification**:
  ```bash
  multiagent-eval evaluate --path industries/telecom --protocol autogen
  ```

### LangChain / LangGraph
- **Protocol**: `langchain://` / `langgraph://`
- **Verification**:
  ```bash
  multiagent-eval evaluate --path industries/telecom --protocol langchain
  ```

### CrewAI
- **Protocol**: `crewai://`
- **Verification**:
  ```bash
  multiagent-eval evaluate --path industries/telecom --protocol crewai
  ```

---

## 💎 Proprietary Model Verification

Verify production readiness for frontier models using live API keys.

| Provider | Protocol | Verification Command |
| :--- | :--- | :--- |
| **OpenAI** | `openai://` | `multiagent-eval run --protocol openai --agent openai://gpt-5.4-mini` |
| **Anthropic**| `claude://` | `multiagent-eval run --protocol claude --agent claude://claude-4-6-sonnet` |
| **Google** | `gemini://` | `multiagent-eval run --protocol gemini --agent gemini://gemini-2.5-flash` |
| **xAI** | `grok://` | `multiagent-eval run --protocol grok --agent grok://grok-4.20-multi-agent` |

---

## ⚖️ Judge & Calibration Audit

For industrial certification, we must verify that the LLM-Judge is aligned with human ground truth.

### 1. Rubric Routing
Run a scenario with a specialized rubric and verify the correct prompt injection in the `run.jsonl` trace.
```bash
multiagent-eval evaluate --path scenarios/clinical_safety_test.json
```

### 2. Calibration Command
Compare judge scores against human labels (if present in the trace).
```bash
multiagent-eval calibrate --path runs/latest_run.jsonl
```
The report will provide **Mean Absolute Error (MAE)** and **Pearson Correlation** for the judge.

---

## ✅ Production Readiness Checklist
- [ ] `multiagent-eval doctor` returns all GREEN.
- [ ] No `ImportError` on any ecosystem adapter.
- [ ] API keys are correctly masked in log outputs.
- [ ] Results generated in `reports/` include required framework metadata.
- [ ] Verification Certificates (VCs) are signed with the project's private key.
