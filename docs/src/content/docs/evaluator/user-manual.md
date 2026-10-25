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
  --path industries/finance/scenarios/loan_scenario.json \
  --agent sse://localhost:5005/stream
```

### 🧩 `run` — Single Scenario
Use this for rapid iteration during prompt engineering or scenario design.
```bash
agentv run --scenario industries/finance/scenarios/loan_v1.json -v
```

### ⏸️ `hitl-resume` — Human-in-the-Loop Resumption
When an evaluation scenario encounters a required human authorization step (e.g., fund transfers or clinical medication orders), runtime state suspends into `PAUSED_FOR_APPROVAL` with an issued `approval_token`. Resume execution after external review:
```bash
agentv hitl-resume --run-id <run_id> --approval-token <token> --decision APPROVED
```

### ⚡ CLI Command Quick Reference
| Category | Command | Purpose |
| :--- | :--- | :--- |
| **Execution** | `evaluate`, `run`, `quickstart` | Running deterministic and batch evaluation suites. |
| **Interactive**| `playground`, `record`, `replay`, `hitl-resume` | Prototyping, manual sessions, playback, and HITL resumption. |
| **Analysis** | `report`, `explain`, `leaderboard`, `trend` | Generating HTML reports, root cause triage, and regression tracking. |
| **Authoring** | `init`, `analyze`, `spec-to-eval`, `auto-translate`, `mutate`, `install` | Scaffolding workspaces, AST repo analysis, PRD parsing, and mutation. |
| **Trust & Audit** | `certify`, `verify`, `verify-package`, `gate` | Cryptographic certification, offline package verification, and CI/CD gating. |
| **Diagnostics**| `doctor`, `lint`, `taxonomy` | Environment diagnostics, AES scenario linting, and failure taxonomies. |

---

## 🖥️ Integrated Visual Suite

The **Visual Console** (launch with `agentv console`) provides a high-density interface for trajectory analysis:

- **Visual AES Builder**: Drag-and-drop node-based interface for designing scenarios.
- **Trajectory Maps**: Interactive React Flow graphs showing every agent turn and tool call.
- **Root Cause Isolation**: One-click focus on the exact "Patient Zero" failing turn.

---

## 📦 Forensic Storage & Vaulting

Run persistence is configured by the active `RunStorageProvider`, not by global
`RUN_LOG_*` switches. Certification requires the provider to supply the exact
canonical trace bytes it committed, scoped lifecycle state, and an atomic
certification transaction.

### 🛠️ Debugging vs. Compliance Workflows

The LocalFile reference provider may retain files for local development, but
neither Core verification nor console reads fall back to those files or to a
master log. Non-local providers expose the same evidence contract without a
shared filesystem layout.

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
