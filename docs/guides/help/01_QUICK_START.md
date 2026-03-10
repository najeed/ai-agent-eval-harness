# 🏁 Quick Start — AI Agent Evaluation Harness

> Get up and running in under 60 seconds. This guide is for people who want to run an evaluation with minimal setup.

---

## 🚀 The 60-Second Demo

The fastest way to see the harness in action is the `quickstart` command. It automatically handles agent setup, scenario execution, and report generation.

```bash
# 1. Install the harness
pip install -e .

# 2. Run the Quickstart
eval-harness quickstart
```

**What happens:**
1. Spawns a sample agent server in the background.
2. Executes a telecom troubleshooting evaluation.
3. Generates a visual HTML report in `reports/`.
4. Shuts down the agent automatically.

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
```bash
eval-harness evaluate --path industries/telecom
```

---

## 📊 Viewing Results

After the run, you'll see a summary in the console and detailed logs in:
- `reports/latest_results.json`
- `runs/run.jsonl` (Flight Recorder)
- `reports/trajectories/` (Visual flows)
- `reports/report_<id>.html` (Rich Visual Report)

---

## 🔍 Replay a Run Trace

Inspect exactly what happened during an evaluation (agent prompts, tool calls, metrics):

```bash
eval-harness replay --path runs/run.jsonl
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
