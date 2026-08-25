---
title: CLI Reference & Command Dispatcher
description: Comprehensive command-line reference for the AgentV enterprise evaluation framework.
---

The `agentv` CLI (also available as `eval-runner`) is the primary entry point for executing evaluations, authoring specifications, diagnosing failures, managing trust protocols, and orchestrating visual debugging sessions.

```bash
agentv <command> [subcommand] [options]
```

---

## 🧭 Global Flags & Post-Quantum Controls

| Flag | Description |
| :--- | :--- |
| `--version` | Display AgentV version (e.g., `AgentV 2.0.0`) and exit. |
| `-h`, `--help` | Display structured usage instructions and available subcommands. |
| `--pqc` | Globally force-enable Hybrid Post-Quantum Cryptography (ML-DSA Dilithium + Ed25519). |
| `--no-pqc` | Force-disable PQC mode and fallback to classical Ed25519 signing. |

---

## 1. 🚀 Executing Evaluations

### `agentv evaluate`
Execute batch evaluations across multiple scenarios with configurable Pass@K trials and protocol bindings.

```bash
agentv evaluate \
  --path scenarios/loan_risk.json \
  --run-id run_fintech_2026_01 \
  --agent http://localhost:5001/execute_task \
  --protocol http \
  --attempts 3 \
  --limit 10 \
  --seed 42 \
  --output reports/fintech_eval.json \
  --pqc
```

#### Options:
- `--path` *(required)*: Path to scenario file (`.json`, `.yaml`), dataset directory, or catalog alias (e.g. `loan_risk`).
- `--agent`: Target agent HTTP URL, socket address, or local command.
- `--protocol`: Agent communication protocol: `http`, `local`, `socket`, `langgraph`, `crewai`, `ag2`.
- `--run-id`: Unique identifier for the evaluation run. Automatically generated if omitted.
- `--attempts`: Number of Pass@K trials per scenario (default: `1`).
- `--limit`: Maximum number of scenarios to evaluate from a dataset.
- `--seed`: Deterministic integer seed for reproducible environment initializations.
- `--format`: Dataset format (`jsonl`, `json`, `yaml`).
- `--output`: File destination for aggregated JSON results (default: `reports/latest_results.json`).
- `--run-log-dir`: Custom directory for raw run logs and telemetry traces (default: `runs/`).
- `--per-run-logs`: Enable isolated per-scenario log directories.
- `--master-log`: Write consolidated master execution log.
- `--plugin`, `--plugins`: Register runtime plugins for the session (can be specified multiple times).
- `-f`, `--force`: Overwrite existing run outputs without prompt.
- `-v`, `--verbose`: Enable debug-level execution logs.

---

### `agentv run`
Execute an isolated evaluation on a single scenario or URI benchmark target.

```bash
agentv run \
  --path industries/healthcare/scenarios/hipaa_compliance.json \
  --agent http://localhost:8000/agent \
  --attempts 1 \
  --verbose
```

#### Options:
- `--path`, `--scenario` *(required)*: Path to scenario file or Benchmark URI (e.g., `gaia://2023_all`).
- `--agent`: Target agent endpoint.
- `--protocol`: Protocol adapter (`http`, `local`, `socket`, etc.).
- `--attempts`: Number of evaluation trials.
- `--seed`: Deterministic random seed.
- `--output`: Custom result summary destination.
- `--run-log-dir`: Custom run log directory.
- `--plugin`: Load external runtime plugins.
- `-v`, `--verbose`: Verbose execution output.

---

### `agentv quickstart`
Run a self-contained 60-second engine demonstration using the built-in mock agent.

```bash
agentv quickstart
```

---

## 2. 📝 Authoring & Scaffolding

### `agentv init`
Scaffold a new evaluation workspace, configure environment templates, and seed industry scenario sets.

```bash
agentv init --dir ./eval-workspace --industry finance --protocol http
```

#### Options:
- `--dir`: Target directory for the workspace.
- `--industry`: Pre-populate domain scenarios (e.g., `finance`, `healthcare`, `cybersecurity`).
- `--protocol`: Default agent communication protocol.
- `--standard`: Target regulatory standard (e.g., `NIST_AI_100_1`, `EU_AI_ACT`).
- `--registry`: Initial upstream registry endpoint.

---

### `agentv analyze`
Scaffold AES scenarios automatically by performing Python AST scans and framework pattern detection on real repositories.

```bash
agentv analyze https://github.com/org/financial-agent --ref main --acquire tree
agentv analyze ./local-agent-code
```

#### Options:
- `url` *(positional or `--path` / `--url`)*: Repository URL or local checkout path.
- `--ref`: Branch, tag, or commit hash for remote repositories.
- `--token-file`: Path to file containing repo access token (`AGENTV_REPO_TOKEN` / `GITHUB_TOKEN`).
- `--acquire`: Source fetching strategy: `tree` (Forge Tree API, fetches only relevant source blobs; recommended for large repos) or `tarball` (full archive).

---

### `agentv spec-to-eval`
Convert unstructured Markdown Product Requirement Documents (PRDs) or specifications into executable AES JSON schemas.

```bash
agentv spec-to-eval --input docs/PRD.md --output scenarios/prd_eval.json
```

#### Options:
- `--input`, `--path`, `--markdown` *(required)*: Source Markdown specification.
- `--output`: Target path for generated AES scenario JSON.

---

### `agentv auto-translate`
Leverage local LLMs to automatically translate documentation into executable AES JSON test suites.

```bash
agentv auto-translate --input docs/api_guide.md --industry telecom --model llama4
```

#### Options:
- `--input`, `--path` *(required)*: Source documentation file.
- `--industry`: Target industry domain for taxonomy tagging.
- `--model`: Local/remote model identifier for translation (default: `llama4`).
- `--output`: Output file destination.

---

### `agentv mutate`
Generate adversarial, edge-case, or perturbed scenario variants from existing baselines.

```bash
agentv mutate --input scenarios/baseline.json --type injection --output scenarios/adversarial.json
```

#### Options:
- `--input`, `--path` *(required)*: Path to baseline scenario JSON.
- `--type` *(required)*: Mutation strategy: `typo`, `injection` (prompt injection), `ambiguity` (underspecified constraints).
- `--output`: Destination path for the mutated scenario.
- `-f`, `--force`: Overwrite existing output file.

---

### `agentv install`
Install signed industry scenario packages from local archive directories or tarballs.

```bash
agentv install ./packs/healthcare_v2.tar.gz
```

#### Options:
- `pack` *(positional)*: Local directory, `.zip`, or `.tar.gz` archive containing `pack.yaml` and verified scenario JSON files.

---

### `agentv scenario`
Generic scenario generation and inspection utilities.

```bash
agentv scenario inspect --path scenarios/loan_risk.json
agentv scenario generate
```

---

## 3. 🔍 Discovery & Exploration

### `agentv list`
List and filter scenarios registered in the local workspace or catalog.

```bash
agentv list --search "fraud" --refresh
```

#### Options:
- `--search`: Search term filter matching title, ID, or description.
- `--refresh`: Force re-indexing of all scenario directories before listing.

---

### `agentv catalog-search`
Search across local and upstream scenario registries.

```bash
agentv catalog-search "kyc verification"
```

---

### `agentv catalog-refresh`
Re-index and synchronize the local scenario catalog index.

```bash
agentv catalog-refresh
```

---

### `agentv inspect`
Display a detailed structural breakdown of a scenario's intent, tasks, required tools, and assertions.

```bash
agentv inspect --path scenarios/loan_risk.json
```

---

### `agentv list-metrics`
Display all registered evaluation metrics and scoring functions.

```bash
agentv list-metrics
```

---

### `agentv taxonomy`
Display the official AgentV / NIST AI 100-1 hierarchical failure taxonomy.

```bash
agentv taxonomy
```

---

### `agentv list-plugins`
Display all currently active and discovered plugins.

```bash
agentv list-plugins
```

---

## 4. 🐞 Debugging & Diagnosis

### `agentv replay`
Deterministically replay a previously recorded evaluation trace step-by-step.

```bash
agentv replay --run-id run_fintech_2026_01
```

---

### `agentv explain`
Perform automated root-cause diagnosis and failure explanation on an evaluation trace.

```bash
agentv explain --run-id run_fintech_2026_01
```

---

### `agentv failures search`
Query the global Failure Corpus to identify historical anti-patterns and known traps.

```bash
agentv failures search "premature_termination"
```

---

### `agentv playground`
Launch an interactive CLI REPL session to communicate directly with an agent.

```bash
agentv playground --agent http://localhost:5001/execute_task --protocol http --verbose
```

---

### `agentv record`
Record live interactive agent sessions directly into an evaluation trace format.

```bash
agentv record --agent http://localhost:5001/execute_task --protocol http
```

---

## 5. 📊 Reporting & Benchmarking

### `agentv report`
Generate standalone, stylized HTML executive reports and Mermaid trajectory graphs from a run trace.

```bash
agentv report --run-id run_fintech_2026_01 --share --pqc
```

#### Options:
- `--run-id` *(required)*: Target evaluation run identifier.
- `--share`: Generate self-contained shareable HTML report bundle.
- `--pqc`: Include Post-Quantum Cryptographic verification proofs.

---

### `agentv leaderboard`
Generate markdown performance leaderboards aggregated across multiple agent evaluation runs.

```bash
agentv leaderboard --dir runs/ --output LEADERBOARD.md
```

#### Options:
- `--dir`: Directory containing evaluation runs (default: `runs`).
- `--output`: Destination markdown file (default: `LEADERBOARD.md`).

---

### `agentv calibrate`
Measure judge agreement against ground-truth human annotations using statistical calibration (Cohen's & Fleiss' Kappa).

```bash
agentv calibrate --run-id run_fintech_2026_01 --golden data/golden_labels.json --plot
```

#### Options:
- `--run-id` *(required)*: Target evaluation run identifier.
- `--golden`: Path to human-annotated golden labels dataset.
- `--plot`: Render visual calibration agreement plots.

---

### `agentv trend`
Detect pass-rate regressions across sequential evaluation runs using ordinary least squares (OLS) regression analysis.

```bash
agentv trend --run-log-dir runs/ --agent "FintechAgent-v2" --window 10 --exit-on-regression --threshold 0.0
```

#### Options:
- `--run-log-dir`, `--dir`: Directory containing run logs (default: `runs`).
- `--agent`: Specific agent name to analyze.
- `--window`: Number of trailing runs in the rolling window (default: `10`).
- `--exit-on-regression`: Exit with non-zero code if negative regression slope exceeds threshold.
- `--threshold`: Maximum allowable negative slope before triggering regression failure (default: `0.0`).

---

## 6. 🛡️ Trust & Verification

### `agentv verify`
Cryptographically verify the integrity of a run trace, evidence ledger, and detached certificate on disk.

```bash
agentv verify --run-id run_fintech_2026_01 --pqc
```

#### Options:
- `--run-id`, `--path` *(required)*: Run identifier or path to run directory.
- `--pqc`: Validate hybrid Post-Quantum signatures in addition to Ed25519.

---

### `agentv certify`
Generate a signed Verification Certificate (VC v3) for a completed evaluation run.

```bash
agentv certify \
  --run-id run_fintech_2026_01 \
  --identity system_id \
  --status pass \
  --score 0.96 \
  --policy-ref NIST-SP-800-218 \
  --ttl 90 \
  --pqc
```

#### Options:
- `--run-id`, `--path` *(required)*: Run identifier.
- `--identity`, `-i`: Signing identity key alias (default: `system_id`).
- `--status`: Certification verdict (`pass`, `fail`, `warning`).
- `--score`: Numeric evaluation score (0.0 - 1.0).
- `--policy-ref`: Governance policy reference ID.
- `--ttl`: Certificate validity time-to-live in days.
- `--fingerprint`: Custom execution environment fingerprint digest.
- `--pqc`: Sign with Hybrid PQC (ML-DSA Dilithium).

---

### `agentv gate`
CI/CD Hard Gatekeeper. Validates trace hashes, sidecar evidence ledgers, and cryptographic certificates, exiting with code `1` upon any tamper or failure.

```bash
agentv gate --run-id run_fintech_2026_01 --verify-ledger --pqc
```

#### Options:
- `--run-id`, `--path` *(required)*: Run identifier.
- `--hash`: Expected SHA3-256 trace hash for tamper detection.
- `--verify-ledger`: Verify every artifact referenced in `evidence_ledger`.
- `--pqc`: Enforce PQC signature verification.

---

### `agentv aes`
Validate scenario definitions against the AES schema and register industry compliance standards.

```bash
agentv aes validate --path scenarios/loan_risk.json --export validation_report.json
agentv aes add-standard --id "FIN_SEC_01" --name "PCI-DSS Tokenization" --industry "finance" --description "Enforces cardholder tokenization"
```

---

### `agentv lint`
Perform static analysis on AES scenario definitions for structural consistency, assertion validity, and schema quality.

```bash
agentv lint --path scenarios/
```

---

## 7. 🔌 Automation & Integration

### `agentv ci generate`
Generate production-ready GitHub Actions or GitLab CI workflow pipelines for automated agent evaluation.

```bash
agentv ci generate
```

---

### `agentv export`
Export evaluation traces and evidence into external formats (Hugging Face Datasets, CSV).

```bash
agentv export --run-id run_fintech_2026_01 --output exports/dataset.csv
```

---

### `agentv import-drift`
Convert uncurated production traces into standard evaluation scenarios for regression prevention.

```bash
agentv import-drift --input logs/prod_trace.jsonl --industry finance
```

---

### `agentv registry`
Synchronize, search, and register upstream scenario repositories.

```bash
agentv registry sync
agentv registry search "healthcare"
agentv registry add --id "enterprise-repo" https://registry.agentvos.ai/packs
```

---

## 8. 💻 Maintenance & Control

### `agentv console`
Launch the interactive Visual Console web server and REST API.

```bash
agentv console --host 127.0.0.1 --port 5000 --debug
```

#### Options:
- `--host`: Bind address (default: `127.0.0.1`).
- `--port`: HTTP listening port (default: `5000`).
- `--debug`: Enable server debug mode and hot-reloading.

---

### `agentv doctor`
Perform an automated health audit of local Python dependencies, virtual environments, cryptographic keys, and scenario registries.

```bash
agentv doctor --registry
```

---

### `agentv cleanup-runs`
Prune old evaluation runs and rotate log artifacts.

```bash
agentv cleanup-runs --days 14 --force
```

#### Options:
- `--days`: Retention window in days (default: `7`).
- `--force`: Bypass confirmation prompt.

---

### `agentv plugin`
Manage external and built-in runtime plugins.

```bash
agentv plugin list
agentv plugin register ./plugins/custom_telemetry
agentv plugin unregister custom_telemetry
```

---

### `agentv contribute`
Start the interactive contributor wizard for creating new scenarios, world shims, and benchmark datasets.

```bash
agentv contribute
```
