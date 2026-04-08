# Developer API & CLI Reference

This document is the authoritative reference for AI engineers using the MultiAgentEval harness. It covers the CLI interface, environment configuration, and public Trust Protocol endpoints.

## CLI Core Interface

The `multiagent-eval` command-line interface is the primary entry point for all evaluation workflows.

### 🚀 Execution Commands

#### `evaluate` — Batch Processing
Run evaluations on one or more scenarios.
```bash
multiagent-eval evaluate --path <path> [--agent <url>] [--protocol <p>] [--attempts K] [--limit N]
```
- `--path`: (Required) Path to scenario file, directory, or `.jsonl` dataset.
- `--agent`: Unified target. Can be a URL (HTTP), a shell command (local), or an address (socket).
- `--protocol`: `http` (default), `local`, `socket`, `autogen`, `crewai`, `langgraph`.
- `--attempts`: Number of pass@k trials per scenario.
- `--limit`: Max number of scenarios to process.
- `--seed`: Random seed for deterministic evaluation.
- `--run-log-dir`: Custom directory for storing trace artifacts (default: `runs`).
- `--per-run-logs`: Force creation of individual `.jsonl` traces per attempt.
- `--master-log`: Append all results to a master `run.jsonl` log.

#### `run` — Single Scenario
Execute a specific scenario or a Benchmark URI (e.g., `gaia://`).
```bash
multiagent-eval run --scenario <path_or_uri> [--attempts K] [--agent-name <name>]
```

#### `record` & `playground` — Interactive Prototyping
- `record`: Log a live session with an agent to a structured trace.
- `playground`: Open an interactive REPL to talk to your agent directly.

#### `replay` — Trace Debugging
Re-execute a `run.jsonl` flight recorder log to debug "wrong turns".

---

### 🛡️ Trust Protocol (Certification & Gating)

The Trust Protocol ensures that evaluations are authentic and tamper-proof.

#### `certify` — Generate Manifest
Signed integrity anchoring for a run.
```bash
multiagent-eval certify --run-id <id> [--private-key <path>] [--fingerprint <id>]
```
- Generates a `run_manifest.json` with SHA-256 binary integrity and optional ED25519 signature.

#### `verify` — Integrity Check
Cryptographic validation of a trace.
```bash
multiagent-eval verify --run-id <id> [--path <path>]
```

#### `gate` — CI/CD Enforcement
The gatekeeper for production deployments. Exits with code `1` on verification failure.
```bash
multiagent-eval gate --run-id <id> --public-key <path> [--hash <commit_sha>]
```
| Command | Description |
|---|---|
| `list-metrics` | Show all registered evaluation metrics and descriptions. |
| `taxonomy` | Display the official AEH failure taxonomy. |
| `ci generate` | Scaffold GitHub Actions workflows for automated evaluation. |

---

### 📂 Specification & Scenario Management

| Command | Description |
|---|---|
| `aes validate` | Validate a scenario against the AES V1.3 schema. |
| `spec-to-eval` | Convert Markdown PRD/Specs into executable JSON. |
| `lint` | Static analysis for scenario quality and compliance. |
| `mutate` | Generate adversarial variants (choices: `typo`, `injection`, `ambiguity`). |
| `inspect` | Display formatted metadata for a specific scenario. |
| `list` | Filter and list available local scenarios (`--search`, `--refresh`). |
| `catalog-search`| Deep search across global scenario metadata. |
| `import-drift` | Convert production traces into evaluation scenarios. |

---

### 📊 Analysis & Reporting

| Command | Description |
|---|---|
| `report` | Generate a stylized HTML report including reconstruction of Mermaid maps. |
| `explain` | AI-powered root cause diagnosis with Tiered Confidence Scoring. |
| `leaderboard` | Aggregate multiple traces (`--dir`) into a performance ranking. |
| `calibrate` | Measure judge agreement against human-labeled ground truth (`--golden`). |

---

### 🛠️ Environment & Utilities

| Command | Description |
|---|---|
| `init` | Scaffold a new benchmark environment and industry registry. |
| `install` | Install curated scenario packs (e.g., `telecom-pack`). |
| `analyze` | Scan a GitHub repository to auto-generate scenarios. |
| `auto-translate`| Use local LLMs (Ollama) to translate technical docs to AES JSON. |
| `doctor` | Audit local dependencies and configuration markers. |
| `plugin` | Register and manage external or built-in plugins. |
| `registry sync` | Synchronize your local library with remote industry standards. |
| `cleanup-runs` | Housekeeping: Prune old traces and log artifacts. |

---

## ⚙️ Environment Configuration (.env)

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Default agent endpoint |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `RUN_LOG_DIR` | `runs` | Directory for execution traces |
| `JUDGE_PROVIDER` | `ollama` | LLM Judge provider (`openai`, `gemini`, `ollama`, etc.) |
| `JUDGE_MODEL` | `llama3` | Specific model for the judge |
| `AEH_STRICT_JAIL` | `0` | Set to `1` for project-only path isolation |

---

## 🌐 Public Trust API (REST)

For external systems (Deployment Gates, Audit Dashboards) that need programmatic verification.

### `GET /api/v1/certificates/<run_id>`
Retrieves the authoritative Verification Certificate (VC) for a specific run.

### `GET /api/v1/verify/<run_id>`
Stateless verification bridge returning the boolean verification status.
