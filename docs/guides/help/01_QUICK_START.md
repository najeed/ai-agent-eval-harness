# 🏁 Quick Start — MultiAgentEval

> Get up and running in under 60 seconds. This guide is for people who want to run an evaluation with minimal setup.

---

## 🚀 The 60-Second Demo

The fastest way to see the harness in action is the `quickstart` command. It automatically handles agent setup, scenario execution, and report generation.

```bash
# 1. Install the harness
pip install -e .

# 2. Run the Quickstart
multiagent-eval quickstart
```

**What happens:**
1. Spawns a **deterministic in-process** sample agent (requires no API keys).
2. Executes a telecom troubleshooting evaluation.
3. Generates a **Premium HTML report** in `reports/` (with Mermaid trajectories).
4. Shuts down the agent automatically. 100% offline-ready.

---

## 🏗️ Building Your Own Suite

When you're ready to start building benchmarks for your own use-case:

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

If you're ready to integrate your own agent, follow these steps.

### 1. Start your Agent
Ensure your agent is running and accessible via an HTTP endpoint.
```bash
# Example (starting the sample agent)
python sample_agent/agent_app.py
```

### 2. Configure Environment
Set the `AGENT_API_URL` to point to your agent.
```bash
# Windows
set AGENT_API_URL=http://localhost:5001/execute_task
```

### 3. Run an Evaluation
Access the global library of **5,000+ industry-grade scenarios**.
```bash
multiagent-eval evaluate --path industries/telecom
```

### 4. Validate Benchmarks
Ensure your custom benchmarks are AES v1.2 compliant.
```bash
multiagent-eval aes validate --path my_benchmarks
```

---

## 📊 Viewing Results

After the run, you'll see a summary in the console and detailed logs in:
- `reports/latest_results.json`
- `runs/run.jsonl` (Flight Recorder)
- `reports/report_<id>.html` (**Premium HTML Report** with trace reconstruction)
- **Interactive Dashboard:** Run `multiagent-eval console` for visual background evaluation and live DNA debugging.

---

## 🔍 Replay a Run Trace

Inspect exactly what happened during an evaluation (agent prompts, tool calls, metrics):

```bash
multiagent-eval replay --path runs/run.jsonl
```

---

## ⚙️ Useful Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint URL |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `RUN_LOG_DIR` | `runs` | Directory for execution traces |

---

## 🧭 Next Steps
- Want more detail? Read the **User Manual**: `docs/guides/help/02_USER_MANUAL.md`
- Planning to extend or contribute? See the **Developer Guide**: `docs/guides/help/03_DEVELOPER_GUIDE.md`
