# CLI Reference: The Industrial User Intent Lifecycle

The `agentv` CLI provides a comprehensive suite of tools for agent evaluation, management, and debugging, organized around the **Industrial User Intent** lifecycle.

## 1. Authoring & Scaffolding
*Intent: I want to create new evaluation scenarios and benchmark environments.*

### `init`
Scaffold a new benchmark directory with starter scenarios for a specific industry.
```bash
agentv init --dir <directory_name> --industry <industry_name> [--protocol <p>]
```

### `scenario`
Generic scenario management, including interactive generation.
```bash
agentv scenario generate
agentv scenario inspect <path>
```

### `spec-to-eval`
Convert Markdown PRD/Spec files into structured AES JSON.
```bash
agentv spec-to-eval --input <path> [--output <scenario.json>]
```

### `mutate`
Generate adversarial or edge-case variants of a base scenario (e.g., typos, prompt injection).
```bash
agentv mutate --input <scenario.json> --type {typo,injection,ambiguity}
```

### `analyze`
Scan an agent's GitHub repository to identify tool patterns and auto-generate matching AES scenarios.
```bash
agentv analyze <github_url>
```

### `auto-translate`
Translate raw technical documents (PDF, MD, TXT) to AES JSON via local LLMs.
```bash
agentv auto-translate --input <path> --model llama4 --industry <industry>
```

---

## 2. Discovery & Exploration
*Intent: I want to find existing scenarios, metrics, or registry information.*

### `list`
Filter and list available scenarios in the local industry registry.
```bash
agentv list [--search <query>] [--refresh]
```

### `catalog-search`
Deep search across the global and local scenario catalogs.
```bash
agentv catalog-search --query <term>
```

### `inspect`
Display architectural details and task breakdown for a specific scenario.
```bash
agentv inspect --scenario-path <path>
```

### `list-metrics`
Display descriptions for all registered evaluation metrics.

### `taxonomy`
Display the official AEH failure taxonomy for categorization.

### `list-plugins`
Display all active and persistently registered plugins.

---

## 3. Executing Evaluations
*Intent: I want to execute evaluations and identify performance baselines.*

### `run`
Execute evaluation on a single specific scenario or Benchmark URI (e.g., `gaia://2023`).
```bash
agentv run --run-id <id> --scenario <path_or_uri> [--attempts K] [--agent-name <name>]
```

### `evaluate`
Execute batch evaluation on a scenario dataset (JSONL/CSV).
```bash
agentv evaluate --run-id <id> --path <dataset_path> [--format {jsonl,csv}] [--attempts K]
```

### `quickstart`
Run a 60-second guided demo that spawns a mock agent and executes an evaluation.

---

## 4. Debugging & Diagnosis
*Intent: I want to understand why a test failed and experiment with fixes.*

### `replay`
Replay a previously recorded run trace (Flight Recorder).
```bash
agentv replay --run-id <id>
```

### `explain`
Diagnose root causes from evaluation traces with high-fidelity tiered scoring.
```bash
agentv explain --run-id <id>
```

### `failures`
Failure Corpus search and analysis utilities.
```bash
agentv failures search <query>
```

### `playground`
Launch an interactive REPL for real-time agent experimentation.
```bash
agentv playground [--agent <url>] [--protocol <p>]
```

### `record`
Record live agent interactions to a session trace.

---

## 5. Reporting & Benchmarking
*Intent: I want to analyze performance and generate shareable artifacts.*

### `report`
Generate a stylized, standalone Premium HTML report from an evaluation trace.
```bash
agentv report --run-id <id> [--share]
```

### `leaderboard`
Generate performance rankings across multiple run traces.
```bash
agentv leaderboard [--dir <path>] [--output <LEADERBOARD.md>]
```

### `trend`
Detect pass-rate regression across sequential evaluation runs using OLS linear regression over a trailing window.
```bash
agentv trend [--run-log-dir <path>] [--agent <agent_name>] [--window <N>] [--exit-on-regression] [--threshold <T>]
```
- `--run-log-dir` / `--dir`: The run log directory to scan (defaults to `runs`).
- `--agent`: Specific agent to analyze. If omitted, computes trends for all agents.
- `--window`: The trailing window of sequential runs to analyze (default: 10).
- `--exit-on-regression`: Exit with code 1 if a regression is detected.
- `--threshold`: The regression threshold for the OLS slope (default: 0.0).

### `calibrate`
Measure and visualize judge agreement against human-labeled ground truth.

---

## 6. Trust & Verification
*Intent: I want to prove the integrity and compliance of my agent results.*

### `verify`
Verify the cryptographic integrity of a run trace using autonomous resolution.
```bash
agentv verify --run-id <id>
```

### `certify`
Generate a cryptographically signed Verification Certificate (VC) for a trace.
```bash
agentv certify --run-id <id> [--identity system_id] [--status {pass,fail,warning}]
```

### `gate`
CI/CD "Hard Gate": Enforce verification and compliance before deployment. Returns exit code 0 or 1.
```bash
agentv gate --run-id <id> [--hash <commit_hash>] [--verify-ledger]
```

### `aes`
AES Specification utilities (Validate/Register).
```bash
agentv aes validate --path <path>
```

### `lint`
Static analysis for AES compliance quality and duplicate detection.

---

## 7. Automation & Integration
*Intent: I want to scale my evaluations and integrate with CI/CD pipelines.*

### `ci`
Scaffold a GitHub Actions workflow for the current environment.
```bash
agentv ci generate
```

### `export`
Export execution traces to external formats (HuggingFace, CSV).
```bash
agentv export --input <run.jsonl> --format hf --output <dataset.json>
```

### `import-drift`
Convert production traces to evaluation scenarios.

### `registry`
Synchronize local industry registries with remote standards.
```bash
agentv registry sync
```

---

## 8. Maintenance & Control
*Intent: I want to manage the environment, plugins, and system health.*

### `console`
Launch the Visual Debugger server (Web UI & REST API).
```bash
agentv console [--host 127.0.0.1] [--port 5000]
```

### `contribute`
Start the interactive contribution wizard for the industry catalog.

### `cleanup-runs`
Prune old traces and rotate log artifacts.
```bash
agentv cleanup-runs [--days 7] [--force]
```

### `doctor`
Audit the local environment for configuration markers and dependencies.

### `plugin`
Manage external and built-in plugins (Register/Unregister/List).
```bash
agentv plugin register <path>
agentv plugin unregister <id>
```
