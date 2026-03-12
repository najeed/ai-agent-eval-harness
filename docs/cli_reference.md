# CLI Reference

The `eval-harness` (or `python -m eval_runner`) CLI provides a comprehensive suite of tools for agent evaluation, management, and debugging.

## Core Commands

### `evaluate`
Run evaluations on one or more scenarios.
```bash
eval-harness evaluate --path <path> [--attempts K] [--limit N] [--verbose]
```
- `--path`: Path to a single Scenario JSON file or a directory containing scenarios.
- `--attempts`: Number of attempts (K) per scenario for `pass@k` calculation.
- `--limit`: Max number of scenarios to run.
- `--protocol`: Agent protocol (`http`, `local`, `socket`).
- `--agent-cmd`: Shell command for `local` protocol.
- `--agent-socket`: Socket address (e.g., `localhost:9000`) or path for `socket` protocol.
- `--format`: Dataset format (`jsonl` or `csv`).

**Research Summary Output:**
When `--attempts` > 1, the harness generates:
- `reports/research_summary.json`: Raw aggregate data.
- `reports/research_summary.md`: A formatted Markdown table of Pass@k, Success Consistency, and Semantic Stability.

### `run`
Execute a single scenario file.
```bash
eval-harness run --scenario <path>
```

### `list`
Search the scenario catalog with keyword and faceted filtering.
```bash
eval-harness list [--search <query>] [--industry <name>] [--difficulty <level>]
```
- `--search`: Keyword search across titles, IDs, and descriptions.
- `--industry`: Filter by industry (e.g., `telecom`, `finance`).
- `--difficulty`: Filter by difficulty level (1-5).

### `lint`
Verify scenario quality and AES specification compliance.
```bash
eval-harness lint <path_to_scenario_or_dir>
```
- Runs automated checks for metadata quality, valid structure, and duplicate detection.
- Provides a quality score (0-100) and detailed warning/error report.

### `init`
Scaffold a new benchmark directory with starter scenarios for a specific industry. Automatically links the scenario to realistic synthetic CSV datasets.
```bash
eval-harness init --dir <directory_name> --industry <industry_name>
```

### `install`
Install curated scenario packs (e.g., `telecom-pack`, `rag-agent-pack`).
```bash
eval-harness install <pack-name>
```
**Example:** `eval-harness install telecom-pack` downloads and registers a bundle of 100+ telecom-specific agent scenarios.

### `analyze`
Scan an agent's GitHub repository to identify tool patterns and auto-generate matching AES scenarios.
```bash
eval-harness analyze <github_url>
```
**Example:** `eval-harness analyze https://github.com/my-org/my-agent` scaffolds scenarios in `scenarios/auto/` based on detected tool definitions.

## Specification & Validation

### `aes validate`
Validate Agent Eval Specification (.aes.yaml) files against the official schema.
```bash
eval-harness aes validate <path>
```

### `spec-to-eval`
Convert a Markdown PRD/Spec file into a structured Scenario JSON.
```bash
eval-harness spec-to-eval --input <prd.md> [--output <scenario.json>]
```
**Example:** Converts a Markdown spec (e.g., *“The agent must verify patient ID and schedule a follow-up if urgent”*) into an AES-compliant `tasks` and `validations` JSON array.

### `auto-translate`
Translate raw, unstructured documents (TXT, MD, PDF, DOCX) into structured Scenario JSON files using a local LLM.
```bash
eval-harness auto-translate --input <document.pdf> --model <model_name> --industry <industry>
```
**Requirement:** `Ollama` must be running locally.

### `ci generate`
Scaffold a `.github/workflows/agent_eval.yml` file to run evaluations automatically on Pull Requests.
```bash
eval-harness ci generate
```

## Drift & Research

### `import-drift`
Convert production traces (interaction logs) into reusable evaluation scenarios.
```bash
eval-harness import-drift --input <trace.json> --industry <industry>
```

### `mutate`
Generate adversarial variants of a scenario (e.g., adding typos, prompt injection).
```bash
eval-harness mutate --input <scenario.json> --type <mutation_type>
```

### `export`
Convert internal execution traces (`run.jsonl`) into externally shareable dataset formats (like HuggingFace Datasets).
```bash
eval-harness export --input <run.jsonl> --format hf --output <dataset.json>
```

### `failures search`
Query the global Failure Corpus to retrieve known failing edge cases for specific topics (e.g., PII, timeouts).
```bash
eval-harness failures search <query>
```
**Example:** `eval-harness failures search "pii leaks"` discovers and imports 5 realistic failing scenarios from the corpus.

## Debugging & Exploration

### `replay`
Re-execute a `run.jsonl` flight recorder log to debug "wrong turns".
```bash
eval-harness replay <path/to/run.jsonl>
```

### `explain`
Automatically analyze a `run.jsonl` trace to diagnose root causes and suggest technical fixes.
```bash
eval-harness explain <path/to/run.jsonl>
```
**Heuristics:** Detects infinite loops, tool-call hallucinations, policy violations, and PII exposure with targeted remediation advice.

### `playground`
Launch an interactive REPL to talk to an agent directly in the terminal.
```bash
eval-harness playground [--agent <url>]
```

### `record`
Record a live interaction with an agent and save it as a structured trace.
```bash
eval-harness record [--agent <url>]
```

## Utilities

### `console`
Launch the Web Admin Console backend API and Unified React SPA. The console provides a high-density dashboard for end-to-end evaluation management:
- **Scenario Explorer**: Browse the catalog with faceted filters, global search, and real-time **Lint Scores**.
- **Visual AES Builder**: Drag-and-drop integrated logic builder that saves production-ready JSON directly to the industry catalog.
- **Background Evaluation**: Trigger runs directly from the UI; the console handles background execution and event streaming.
- **Visual Debugger**: Real-time trajectory playback with interactive state inspection powered by the `DebuggerStateStore`.
```bash
eval-harness console [--host 127.0.0.1] [--port 5000]
```

### `doctor`
Check the local environment for missing dependencies or configuration issues.
```bash
eval-harness doctor
```

### `quickstart`
Run a 60-second guided demo that spawns a mock agent and executes an evaluation.
```bash
eval-harness quickstart
```

### `report`
Generate a standalone Premium HTML report from an execution trace.
```bash
eval-harness report <path/to/run.jsonl>
```
**Feature Highlights:**
- **Trace Reconstruction**: Automatically reconstructs hierarchical task results, metrics, and triage tags from historical JSONL events.
- **Visual Trajectories**: Generates interactive Mermaid maps for every task in the trace.

### `scenario generate`
Interactively workspace to generate new test scenarios via a terminal wizard.
```bash
eval-harness scenario generate
```

## Plugin Commands

### `plugin <name> <command>`
Execute plugin-specific subcommands. Plugins register their own commands under a secure namespace to prevent command hijacking.
```bash
eval-harness plugin <plugin_name> <command> [options]
```

> **Security Note:** All plugin commands are namespaced under `eval-harness plugin <name>` to prevent command hijacking. The legacy `extend_cli` hook has been removed.

