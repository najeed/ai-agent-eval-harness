---
title: CLI Reference
description: Command-line interface for industrial-grade agent evaluation and analysis.
---

The `multiagent-eval` CLI is the primary entry point for all evaluation workflows, providing tools for execution, specification, and forensic analysis.

## 🚀 Execution Commands

### `evaluate`
Run evaluations on one or more industrial scenarios.
```bash
multiagent-eval evaluate \
  --run-id <id> \
  --agent http://localhost:5001/execute_task \
  --attempts 3 \
  --limit 10
```
- `--path`: (Required) Path to scenario file, directory, or `.jsonl` dataset.
- `--agent`: The target agent URL or local command.
- `--protocol`: `http` (default), `local`, `socket`, `langgraph`, `crewai`.
- `--attempts`: Pass@K trials per scenario.

### `run`
Execute a single specific scenario or a [Benchmark URI](/ai-agent-eval-harness/extender/api-reference/).
```bash
multiagent-eval run --scenario gaia://2023_all
```

### `record` & `playground`
- **`record`**: Manually log a live agent session to create a new benchmark trace.
- **`playground`**: Interactive REPL to communicate directly with an agent for rapid prototyping.

---

## 🛡️ Trust Protocol (Certification)

### `certify`
Generate an immutable Verification Certificate (VC) for a specific run.
```bash
multiagent-eval certify --run-id <id> --status pass --score 0.95
```

### `verify` & `gate`
- **`verify`**: Cryptographically validate the integrity of a run trace.
- **`gate`**: CI/CD gatekeeper. Exits with code `1` if verification fails.

---

## 📂 Specification & Scenario Management

### `spec-to-eval`
Convert Markdown PRDs/Specs into executable AES JSON using [Hybrid Parsing](/ai-agent-eval-harness/evaluator/aes-spec/).
```bash
multiagent-eval spec-to-eval --input prd.md --output scenario.json --fill-defaults
```

### `import-drift`
Convert production traces into evaluation scenarios for [Regression Testing](/ai-agent-eval-harness/evaluator/drift/).

---

## 📊 Analysis & Reporting

### `report`
Generate stylized HTML reports and Mermaid trajectory maps.
```bash
multiagent-eval report --run-id <id> --share
```

### `explain`
AI-powered root cause diagnosis with [Tiered Confidence Scoring](/ai-agent-eval-harness/evaluator/drift/).

---

## 🛠️ Environment Utilities

### `doctor`
Audit local dependencies, environment variables, and configuration health.
```bash
multiagent-eval doctor
```

### `init`
Scaffold a new benchmark environment and industry registry.
```bash
multiagent-eval init --industry fintech
```
