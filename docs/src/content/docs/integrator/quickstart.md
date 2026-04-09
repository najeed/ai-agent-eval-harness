---
title: Quick Start
description: Get up and running with MultiAgentEval in under 60 seconds.
---

This guide is for developers and evaluators who want to see MultiAgentEval in action with minimal setup.

## 🚀 The 60-Second Demo

The fastest way to explore the harness is the `quickstart` command. It handles agent setup, scenario execution, and report generation automatically.

```bash
# 1. Install the harness
pip install -e .

# 2. Run the Quickstart
multiagent-eval quickstart
```

### What Happens:
1.  **Sample Agent**: Spawns a deterministic, in-process sample agent (no API keys required).
2.  **Execution**: Runs a telecom troubleshooting evaluation from the industrial library.
3.  **Reporting**: Generates a **Premium HTML report** (with Mermaid maps) in the `reports/` directory.
4.  **Cleanup**: Automatically shuts down the agent.

---

## 🏗️ Building Your Own Suite

When you're ready to build benchmarks for your specific industrial use case:

### 1. Scaffold the Project
Generate a starter workspace with realistic industry datasets.
```bash
multiagent-eval init --dir my_benchmarks --industry finance
```

### 2. Auto-Translate Existing Specs
Convert PDF or Markdown PRDs into executable AES JSON scenarios (requires [Ollama](https://ollama.com/)).
```bash
multiagent-eval auto-translate --input specs/loan_approval.pdf --industry finance
```

---

## 🛠️ Manual Integration

To connect your own agent to the harness:

1.  **Start Your Agent**: Ensure it follows the [Agent API Contract](/ai-agent-eval-harness/integrator/agent-contract/).
2.  **Configure `.env`**: Point `AGENT_API_URL` to your endpoint.
    ```bash
    AGENT_API_URL=http://localhost:5001/execute_task
    ```
3.  **Run Evaluation**: Use scenarios from the [Industrial Library](/ai-agent-eval-harness/evaluator/industries/).
    ```bash
    multiagent-eval evaluate --path industries/telecom
    ```
4.  **Analyze Results**: Replay a trace to debug agent reasoning.
    ```bash
    multiagent-eval replay --path runs/run.jsonl
    ```

---

## 🧭 Next Steps
- **Evaluators**: Read the [User Manual](/ai-agent-eval-harness/evaluator/user-manual/) for advanced analysis.
- **Architects**: Dive into the [Core Architecture](/ai-agent-eval-harness/builder/architecture/).
- **Extenders**: Learn how to write [Custom Shims](/ai-agent-eval-harness/extender/shimming/).
