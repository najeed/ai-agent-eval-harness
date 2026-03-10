# 🚀 Quick Start — AI Agent Evaluation Harness

> Get up and running in under 5 minutes. This guide is for people who want to run an evaluation with minimal setup.

---

## ✅ 1) Prerequisites

- **Python 3.8+**
- **pip**
- (Optional) **Docker & docker-compose** for the full lab experience

---

## 🧩 2) Install & Run

### 2.1 Clone + Install

```bash
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness
pip install -e .
pip install -r requirements.txt
```

### 2.2 (Optional) Start the Full Lab with Docker

This spins up the harness, a sample agent, and the dashboard.

```bash
docker-compose up -d
```

### 2.3 Run a Quick Evaluation

Use a built-in industry scenario set (e.g., `telecom`):

```bash
eval-harness evaluate --path industries/telecom --export
```

> ✅ Output is generated under `reports/` (JSON, trajectories, heatmaps).

---

## 🧪 3) Run a Single Scenario (Fast Feedback)

Run one scenario file and get immediate output:

```bash
eval-harness run scenarios/starter_scenario.json
```

---

## 🔍 4) Replay a Run Trace

Inspect exactly what happened during an evaluation (agent prompts, tool calls, metrics):

```bash
eval-harness replay --path runs/run.jsonl
```

---

## ⚙️ 5) Useful Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint URL |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |

---

## 🧭 Next Steps
- Want more detail? Read the **User Manual**: `docs/guides/help/02_USER_MANUAL.md`
- Planning to extend or contribute? See the **Developer Guide**: `docs/guides/help/03_DEVELOPER_GUIDE.md`
