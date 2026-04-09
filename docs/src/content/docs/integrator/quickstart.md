---
title: Quick Start
description: Get up and running with MultiAgentEval in under 60 seconds.
---

import { Steps } from '@astrojs/starlight/components';

This guide is designed for **Agent Integrators** who want to run their first evaluation with minimal setup.

---

## 🚀 The 60-Second Demo

The fastest way to see the harness in action is the `quickstart` command. It automatically handles agent setup, scenario execution, and report generation using an in-process mock agent.

<Steps>
1. **Install the harness**
   ```bash
   pip install -e .
   ```

2. **Run the Quickstart**
   ```bash
   multiagent-eval quickstart
   ```
</Steps>

**What happens:**
- Spawns a **deterministic in-process** sample agent (no API keys required).
- Executes a telecom troubleshooting evaluation.
- Generates a **Premium HTML report** in `reports/` with Mermaid trajectories.
- 100% offline-ready.

---

## 🏗️ Building Your Own Suite

When you're ready to start building benchmarks for your specific industrial use-case:

### 1. Scaffold the Project
Generate a starter workspace linked to automatically generated realistic datasets.
```bash
multiagent-eval init --dir my_benchmarks --industry finance
```

### 2. Auto-Translate Existing Specs
If you already have PDF or Markdown guidelines, convert them into JSON scenarios automatically (requires local `Ollama`):
```bash
multiagent-eval auto-translate --input specs/loan_approval.pdf --industry finance
```

---

## 🛠 Manual Setup (The "Standard" Way)

Use this method to integrate your own production agents into the harness.

### 1. Start your Agent
Ensure your agent is running and accessible via an HTTP endpoint.
```bash
# Example (starting the sample agent)
python sample_agent/agent_app.py
```

### 2. Configure Environment
Set the `AGENT_API_URL` to point to your agent endpoint.
```bash
# Windows
set AGENT_API_URL=http://localhost:5001/execute_task
```

### 3. Run an Evaluation
Access the global library of industry-grade scenarios.
```bash
multiagent-eval evaluate --path industries/telecom
```

---

## 📊 Viewing Results

After the run, you'll find results in the following locations:

- **Flight Recorder**: `runs/run.jsonl` (raw execution trace).
- **Executive Summaries**: `reports/latest_results.json`.
- **Visual Reports**: `reports/report_<id>.html` (includes trace reconstruction).
- **Interactive Dashboard**: Run `multiagent-eval console` for live DNA debugging and visual background evaluation.

---

## ⚙️ Core Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint URL |
| `EVAL_MAX_TURNS` | `10` | Max conversation turns per task (v1.3 default) |
| `RUN_LOG_DIR` | `runs` | Directory for execution traces |

---

## 🧭 Next Steps
- **Agent Contract**: Learn how to implement the standard API in [Agent Contract](../integrator/agent-contract/).
- **Auditing**: Learn about trace verification in the [Trust Protocol](../../auditor/trust-protocol/).
