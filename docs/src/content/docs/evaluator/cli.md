---
title: CLI Reference
description: Command-line interface for industrial-grade agent evaluation and analysis.
---

The `agentv` CLI is the primary entry point for all evaluation workflows, providing tools for execution, specification, and forensic analysis.

## 🚀 Execution Commands

### `evaluate`
Run evaluations on one or more industrial scenarios.
```bash
agentv evaluate \
  --path scenarios/loan_scenario.json \
  --run-id <id> \
  --agent http://localhost:5001/execute_task \
  --attempts 3 \
  --limit 10
```
- `--path`: (Required) Scenario ID alias (e.g., `loan_risk`) OR a project-relative path (e.g., `industries/fin/scenarios/loan.json`).
- `--scenario`: Alias for Scenario ID or project-relative path (used in `run` and `inspect`).
- *Note*: Scenario IDs are resolved against the catalog index. If an ID is missing or the catalog is stale, you can optionally refresh it using `agentv list` or `agentv catalog-refresh`.
- `--agent`: The target agent URL or local command.
- `--protocol`: `http` (default), `local`, `socket`, `langgraph`, `crewai`.
- `--attempts`: Pass@K trials per scenario.

### `run`
Execute a single specific scenario or a [Benchmark URI](/extender/api-reference/).
```bash
agentv run --scenario gaia://2023_all
```

### `record` & `playground`
- **`record`**: Manually log a live agent session to create a new benchmark trace.
- **`playground`**: Interactive REPL to communicate directly with an agent for rapid prototyping.

---

## 🛡️ Trust Protocol (Certification)

### `certify`
Generate an immutable Verification Certificate (VC) for a specific run.
```bash
agentv certify --run-id <id> --status pass --score 0.95
```

### `verify` & `gate`
- **`verify`**: Cryptographically validate the integrity of a run trace.
- **`gate`**: CI/CD gatekeeper. Exits with code `1` if verification fails.

---

## 📂 Specification & Scenario Management

### `spec-to-eval`
Convert Markdown PRDs/Specs into executable AES JSON using [Hybrid Parsing](/evaluator/aes-spec/).
```bash
agentv spec-to-eval --input prd.md --output scenario.json --fill-defaults
```

### `import-drift`
Convert production traces into evaluation scenarios for [Regression Testing](/evaluator/drift/).

---

## 📊 Analysis & Reporting

### `report`
Generate stylized HTML reports and Mermaid trajectory maps.
```bash
agentv report --run-id <id> --share
```

### `leaderboard`
Generate performance rankings from run traces in a target directory.
```bash
agentv leaderboard --dir runs/ --output LEADERBOARD.md
```

### `trend`
Detect pass-rate regression across sequential evaluation runs.
```bash
agentv trend \
  --run-log-dir runs/ \
  --window 10 \
  --exit-on-regression \
  --threshold 0.0
```
- `--run-log-dir` / `--dir`: The run log directory to scan (defaults to `runs`).
- `--agent`: Specific agent to analyze.
- `--window`: The trailing window of sequential runs (default: 10).
- `--exit-on-regression`: Exit with code 1 if regression is detected.
- `--threshold`: The regression threshold for the OLS slope (default: 0.0).

### `explain`
AI-powered root cause diagnosis with [Tiered Confidence Scoring](/evaluator/drift/).

---

## 🛠️ Environment Utilities

### `doctor`
Audit local dependencies, environment variables, and configuration health.
```bash
agentv doctor
```

### `init`
Scaffold a new benchmark environment and industry registry.
```bash
agentv init --industry fintech
```
