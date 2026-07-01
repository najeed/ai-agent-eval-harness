---
title: Ecosystem Verification
description: Step-by-step instructions to verify third-party integrations, adapters, and environment health.
---

This guide provides the protocols for verifying that your AgentV environment is production-ready across all framework adapters and proprietary models.

## 🚦 Prerequisites

### Environment Setup
Ensure the harness is installed in editable mode and all API keys are configured in your `.env` file.
```bash
pip install -e .
```

### Dependency Audit
Use the `doctor` utility to perform a global health check of your dependencies and connection status.
```bash
agentv doctor
```

---

## 🌎 Framework Verification (Adapters)

Verify that the harness can communicate with external frameworks using the appropriate protocols.

### AG2 (formerly AutoGen)
- **Protocol**: `ag2`
- **Verification**:
  ```bash
  agentv run --path scenarios/loan_scenario.json --protocol ag2
  ```

### LangChain / LangGraph
- **Protocol**: `langgraph`
- **Verification**:
  ```bash
  agentv run --path scenarios/loan_scenario.json --protocol langgraph
  ```

### CrewAI
- **Protocol**: `crewai`
- **Verification**:
  ```bash
  agentv run --path scenarios/loan_scenario.json --protocol crewai
  ```

---

## 💎 Proprietary Model Verification

Verify production readiness for frontier models using live API keys.

| Provider | Protocol | Verification Command |
| :--- | :--- | :--- |
| **OpenAI** | `openai://` | `agentv run --protocol openai --agent openai://gpt-5.4-mini` |
| **Anthropic**| `claude://` | `agentv run --protocol claude --agent claude://claude-4.6-sonnet` |
| **Google** | `gemini://` | `agentv run --protocol gemini --agent gemini://gemini-2.5-flash` |
| **xAI** | `grok://` | `agentv run --protocol grok --agent grok://grok-4.20-multi-agent` |

---

## ⚖️ Judge & Calibration Audit

For industrial certification, we must verify that the LLM-Judge is aligned with human ground truth.

### 1. Rubric Routing
Run a scenario with a specialized rubric and verify the correct prompt injection in the `run.jsonl` trace.
```bash
agentv evaluate --run-id <id>
```

### 2. Calibration Command
Compare judge scores against human labels (if present in the trace).
```bash
agentv calibrate --run-id <id>
```
The report will provide **Mean Absolute Error (MAE)** and **Pearson Correlation** for the judge.

---

## ✅ Production Readiness Checklist
- [ ] `agentv doctor` returns all GREEN.
- [ ] No `ImportError` on any ecosystem adapter.
- [ ] API keys are correctly masked in log outputs.
- [ ] Results generated in `reports/` include required framework metadata.
- [ ] Verification Certificates (VCs) are signed with the project's private key.
