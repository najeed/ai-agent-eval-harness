---
title: User Manual
description: Comprehensive guide for evaluators to run, analyze, and troubleshoot agent evaluations.
---

This manual is for users who want to run and understand evaluations without diving into the internal code base.

## 📚 Core Concepts

### 🗂️ The Scenario (AES)
The unit of evaluation. A JSON or YAML file mapping to the **Agent Evaluation Specification**.
- **`scenario_id`**: Unique identifier.
- **`industry`**: Context (e.g., `telecom`, `finance`).
- **`dataset`**: (Optional) Path to synthetic CSV/JSONL data. Supports [Path Decoupling](/evaluator/aes-spec/).
- **`tasks`**: Ordered steps the agent must achieve.

### ✅ The Task
A specific step within a scenario.
- **`description`**: The prompt or instruction sent to the agent.
- **`success_criteria`**: The metrics and thresholds for determination of success.
- **`required_tools`**: Tools the agent is expected to use (monitored via `tool_call_correctness`).

---

## ▶️ Running Evaluations (CLI)

### 🧪 `evaluate` — Batch Execution
Run a suite of scenarios across a directory or industry registry.
```bash
agentv evaluate \
  --run-id <id> \
  --agent http://localhost:5001/execute_task \
  --attempts 3 \
  --limit 10
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
| **Analysis** | `report`, `explain`, `leaderboard` | Viewing results. |
| **Diagnostics**| `doctor`, `lint`, `verify` | Environment and integrity checks. |

---

## 🖥️ Integrated Visual Suite

The **Visual Console** (launch with `agentv console`) provides a high-density interface for trajectory analysis:

- **Visual AES Builder**: Drag-and-drop node-based interface for designing scenarios.
- **Trajectory Maps**: Interactive React Flow graphs showing every agent turn and tool call.
- **Root Cause Isolation**: One-click focus on the exact "Patient Zero" failing turn.

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
