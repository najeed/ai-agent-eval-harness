---
title: User Manual
description: Comprehensive guide for evaluators to run, analyze, and troubleshoot agent evaluations.
---

This manual is for users who want to run and understand evaluations without diving into the internal code base.

## 📚 Core Concepts

### 🗂️ The Scenario (AES)
The unit of evaluation. A JSON or YAML file mapping to the **Agent Evaluation Specification**.
- **`metadata`**: Scenario identifier and compliance capabilities. Supports [Path Decoupling](/evaluator/aes-spec/).
- **`workflow`**: DAG containing a series of `nodes` and dependency `edges`.

### ✅ The Task Node
A specific step within the workflow DAG.
- **`task_description`**: The prompt or instruction sent to the agent.
- **`success_criteria`**: The metrics and thresholds for determination of success.
- **`expected_outcome`**: (Optional) Standard cryptographic outcome or verifiably expected state.

---

## ▶️ Running Evaluations (CLI)

### 🧪 `evaluate` — Batch Execution
Run a suite of scenarios across a directory or industry registry.
```bash
agentv evaluate \
  --path scenarios/loan_scenario.json \
  --run-id <id> \
  --agent http://localhost:5001/execute_task \
  --attempts 3 \
  --limit 10

# SSE Streaming Agent
agentv evaluate \
  --path scenarios/loan_scenario.json \
  --agent sse://localhost:5005/stream \
  --industry finance
```

### 🧩 `run` — Single Scenario
Use this for rapid iteration during prompt engineering or scenario design.
```bash
agentv run --scenario industries/finance/scenarios/loan_v1.json -v
```

### ⚡ CLI Command Quick Reference
| Category | Command | Purpose |
| :--- | :--- | :--- |
| **Execution** | `evaluate`, `run`, `quickstart` | Running tests. |
| **Interactive**| `playground`, `record`, `replay` | Prototyping and debugging. |
| **Analysis** | `report`, `explain`, `leaderboard`, `trend` | Viewing results and detecting regression. |
| **Diagnostics**| `doctor`, `lint`, `verify` | Environment and integrity checks. |

---

## 🖥️ Integrated Visual Suite

The **Visual Console** (launch with `agentv console`) provides a high-density interface for trajectory analysis:

- **Visual AES Builder**: Drag-and-drop node-based interface for designing scenarios.
- **Trajectory Maps**: Interactive React Flow graphs showing every agent turn and tool call.
- **Root Cause Isolation**: One-click focus on the exact "Patient Zero" failing turn.

---

## 📦 Forensic Storage & Vaulting

AgentV uses a **Strict Vault Architecture** to isolate and protect forensic traces. This is controlled primarily by the `FlightRecorderPlugin` and ensures that all execution artifacts for a specific run are contained within a single directory.

### Configuration Tiers

| Option | Default | Purpose |
| :--- | :--- | :--- |
| `RUN_LOG_PER_RUN` | `true` | Creates a nested "Vault" directory (`runs/<run_id>/`) for every execution. |
| `RUN_LOG_MASTER` | `true` | Appends all system events to a consolidated `runs/run.jsonl` file. |

### 🛠️ Debugging vs. Compliance Workflows

The vault architecture can be tuned based on your current project lifecycle:

#### **1. Debugging & Iteration (Zero Pollution)**
When iterating rapidly on prompts or scenario designs, you can disable per-run vaulting to keep your `runs/` workspace clean.
- **Configure**: Set `RUN_LOG_PER_RUN=false`.
- **Benefit**: No new subdirectories are created. The workspace remains clean of "transient" vaults.
- **Trace Access**: You can still replay or analyze the last run via the **Master Log Fallback**, as the engine will automatically extract the relevant events from the consolidated `run.jsonl`.

#### **2. Compliance & Audit-Grade (Isolated Vaults)**
In production verification or formal publication phases, per-run vaulting is **mandatory**.
- **Configure**: Set `RUN_LOG_PER_RUN=true`.
- **Benefit**: Each run is physically isolated in its own vault. This is required for cryptographic certification (`agentv certify`), as it enables high-fidelity hashing of the trace and its sidecar artifacts.
- **Trace Access**: High-speed, prioritized resolution from the vault's local `run.jsonl`.

---

## 🔍 Drift & Triage

### Import Drift
Convert production traces into actionable evaluation scenarios for regression testing.
```bash
agentv import-drift --input logs.jsonl --industry healthcare
```

### The Triage Engine
AgentV isolates failures by combining three layers:
1.  **State Layer (VFS)**: Compares physical sandbox changes against expectations.
2.  **Logic Layer**: Detects reasoning loops and infinite re-planning stalls.
3.  **Security Layer**: Pinpoints guardrail violations and PII leaks.

## 📊 Metrics Explained

- **`policy_compliance`**: Ensures the agent adhered to governance rules.
- **`state_verification`**: Validates deep state changes using dot-notation.
- **`luna_judge_score`**: Semantic verification using a calibrated LLM-Judge.
- **`delegation_loop_risk`**: Detects infinite cycles in multi-agent handoffs.
