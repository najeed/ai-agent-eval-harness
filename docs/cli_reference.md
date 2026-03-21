# CLI Reference

The `multiagent-eval` (or `python -m eval_runner`) CLI provides a comprehensive suite of tools for agent evaluation, management, and debugging.

## Core Commands

### `evaluate`
Run evaluations on one or more scenarios.
```bash
multiagent-eval evaluate --path <path> [--attempts K] [--limit N] [--verbose]
```
- `--path`: Path to a single Scenario JSON file, a directory containing scenarios, or a Benchmark URI (e.g., `gaia://2023`). Supports Path Decoupling: If a scenario is located outside the standard `/industries` directory, the harness automatically resolves relative dataset paths and tags the scenario as `local`/`unclassified`.
- `--attempts`: Number of attempts (K) per scenario for `pass@k` calculation.
- `--limit`: Max number of scenarios to run.
- `--agent-name`: Human-readable name for the agent (for reports and leaderboards). Priority: CLI Flag > Zero-Touch Discovery > Endpoint URL.

**Environment Variables:**
| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint for `http` protocol |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `JUDGE_PROVIDER` | `ollama` | LLM Judge provider (`openai`, `anthropic`, `gemini`, `ollama`, `grok`) |
| `JUDGE_MODEL` | - | Specific model for the judge (e.g., `gpt-4o`, `claude-3-5-sonnet`) |
| `LUNA_JUDGE_TEMPERATURE`| `0.0` | Temperature for judge generation |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama service endpoint |
| `OPENAI_API_KEY` | - | API key for OpenAI provider |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for OpenAI-compatible APIs |
| `ANTHROPIC_API_KEY`| - | API key for Anthropic/Claude provider |
| `GOOGLE_API_KEY` | - | API key for Google/Gemini provider |
| `XAI_API_KEY` | - | API key for xAI/Grok provider |
| `AUTOGEN_API_URL` | `http://localhost:5002/execute_task` | Endpoint for `autogen` protocol |
| `DEFAULT_ADAPTER_TIMEOUT`| `30` | Network timeout for agent adapters |

- `--protocol`: Agent protocol (e.g., `http`, `local`, `socket`, `autogen`, `langgraph`, etc.). **Note:** All ecosystem adapters are discovery-driven; the CLI dynamically populates these choices from available plugins.
- `--agent`: Unified agent target. Can be a URL (for `http`, `autogen`, `langgraph`), a shell command (for `local`), or an address (for `socket`).
- `--agent-cmd`: (Legacy) Shell command for `local` protocol.
- `--agent-socket`: (Legacy) Socket address for `socket` protocol.
- `--format`: Dataset format (`jsonl` or `csv`).

**Research Summary Output:**
When `--attempts` > 1, the harness generates:
- `reports/research_summary.json`: Raw aggregate data.
- `reports/research_summary.md`: A formatted Markdown table of Pass@k, Success Consistency, and Semantic Stability.

### `run`
Execute a single scenario file or a Benchmark URI.
```bash
multiagent-eval run --scenario <path_or_uri>
```
**Example (Benchmark):** `multiagent-eval run --scenario gaia://2023` (Executes all scenarios in the GAIA 2023 benchmark).

### `list`
Search the scenario catalog with keyword and faceted filtering.
```bash
multiagent-eval list [--search <query>]
```
- `--search`: Search scenarios by title, industry, or tags.
- `--refresh`: Rebuild the scenario index from source.

### `lint`
Verify scenario quality and AES specification compliance.
```bash
multiagent-eval lint --path <path_to_scenario_or_dir>
```
- Runs automated checks for metadata quality, valid structure, and duplicate detection.
- Provides a quality score (0-100) and detailed warning/error report.

### `init`
Scaffold a new benchmark directory with starter scenarios for a specific industry. Automatically links the scenario to realistic synthetic CSV datasets.
```bash
multiagent-eval init --dir <directory_name> --industry <industry_name>
```

### `install`
Install curated scenario packs (e.g., `telecom-pack`, `rag-agent-pack`).
```bash
multiagent-eval install <pack-name>
```
**Example:** `multiagent-eval install telecom-pack` downloads and registers a bundle of 100+ telecom-specific agent scenarios.

### `analyze`
Scan an agent's GitHub repository to identify tool patterns and auto-generate matching AES scenarios.
```bash
multiagent-eval analyze <github_url>
```
**Example:** `multiagent-eval analyze https://github.com/my-org/my-agent` scaffolds scenarios in `scenarios/auto/` based on detected tool definitions.

## Specification & Validation

### `aes validate`
Validate Agent Eval Specification (.aes.yaml) files against the official schema.
```bash
multiagent-eval aes validate --path <path>
```
- Performs deep structure checking using `jsonschema`.
- Ensures all mandatory benchmark fields are present.

### `aes scaffold`
Automatically generate a template Agent Eval Specification (.aes.yaml) file.
```bash
multiagent-eval aes scaffold --output <path>
```
- Creates a baseline YAML structure compliant with the latest benchmark standards.

### `spec-to-eval`
Convert a Markdown PRD/Spec file into a structured Scenario JSON.
```bash
multiagent-eval spec-to-eval --input <prd.md> [--output <scenario.json>] [--fill-defaults]
```
- `--input`: Path to the Markdown specification file.
- `--output`: Optional. Custom output path for the generated JSON.
- `--fill-defaults`: Optional. Automatically populates mandatory AES fields.
- Intelligent Classification: The command includes a Semantic Similarity Classifier (using `sentence-transformers`) that automatically identifies `industry`, `use_case`, and `core_function` from the spec's conceptual context (e.g., distinguishing between `finance` and `legal` based on the nature of the request).

### `auto-translate`
Translate raw, unstructured documents (TXT, MD, PDF, DOCX) into structured Scenario JSON files using a local LLM.
```bash
multiagent-eval auto-translate --input <document.pdf> --model <model_name> --industry <industry>
```
**Requirement:** `Ollama` must be running locally.

### `ci generate`
Scaffold a `.github/workflows/agent_eval.yml` file to run evaluations automatically on Pull Requests.
```bash
multiagent-eval ci generate
```

## Drift & Research

### `import-drift`
Convert production traces (interaction logs) into reusable evaluation scenarios.
```bash
multiagent-eval import-drift --input <trace.json> --industry <industry>
```

### `mutate`
Generate adversarial variants of a scenario (e.g., adding typos, prompt injection).
```bash
multiagent-eval mutate --input <scenario.json> --type <mutation_type>
```

### `export`
Convert internal execution traces (`run.jsonl`) into externally shareable dataset formats (like HuggingFace Datasets).
```bash
multiagent-eval export --input <run.jsonl> --format hf --output <dataset.json>
```

### `failures search`
Query the global Failure Corpus to retrieve known failing edge cases for specific topics (e.g., PII, timeouts).
```bash
multiagent-eval failures search <query>
```
**Example:** `multiagent-eval failures search "pii leaks"` discovers and imports 5 realistic failing scenarios from the corpus.

## Debugging & Exploration

### `replay`
Re-execute a `run.jsonl` flight recorder log to debug "wrong turns".
```bash
multiagent-eval replay --path <path/to/run.jsonl>
```

### `explain`
Automatically analyze a `run.jsonl` trace to diagnose root causes with high-fidelity tiered scoring and actionable technical fixes.
```bash
multiagent-eval explain --path <path/to/run.jsonl>
```
**Forensic Features:**
- **Tiered Confidence Scoring**: Distinguishes between explicit policy violations (100%), induced system/tool errors (85%), and heuristic fallbacks (50%).
- **Actionable Recommendations**: Provides targeted remediation advice (e.g., prompt refinement, tool sandbox optimization) based on the identified failure pattern.
- **Pinpoint Diagnostics**: Identifies the exact turn (index) in the trajectory where the failure logic diverged.

### `calibrate`
Measure alignment between the LLM judge and human ground truth in a flight recorder log.
```bash
multiagent-eval calibrate --path <path/to/run.jsonl>
```
**Metrics:** Calculates Pearson Correlation and Mean Absolute Error (MAE) based on paired `luna_judge_score` and `human_score` events.

### `playground`
Launch an interactive REPL to talk to an agent directly in the terminal.
```bash
multiagent-eval playground [--agent <url>]
```

### `record`
Record a live interaction with an agent and save it as a structured trace.
```bash
multiagent-eval record [--agent <url>]
```

## Utilities

### `console`
Launch the Visual Debugger backend API and Unified React SPA. The debugger provides a high-density dashboard for end-to-end evaluation management:
- **Scenario Explorer**: Browse the catalog with faceted filters, global search, and real-time **Lint Scores**.
- **Visual AES Builder**: Drag-and-drop integrated logic builder that saves production-ready JSON directly to the industry catalog.
- **Background Evaluation**: Trigger runs directly from the UI; the console handles background execution and event streaming.
- **Visual Debugger**: Real-time trajectory playback with interactive state inspection powered by the `DebuggerStateStore`.
```bash
multiagent-eval console [--host 127.0.0.1] [--port 5000]
```

### `doctor`
Check the local environment for missing dependencies or configuration issues.
```bash
multiagent-eval doctor
```

### `quickstart`
Run a 60-second guided demo that spawns a mock agent and executes an evaluation.
```bash
multiagent-eval quickstart
```

### `report`
Generate a standalone Premium HTML report from an execution trace.
```bash
multiagent-eval report --path <path/to/run.jsonl>
```
**Feature Highlights:**
- **Trace Reconstruction**: Automatically reconstructs hierarchical task results, metrics, and triage tags from historical JSONL events.
- **Visual Trajectories**: Generates interactive Mermaid maps for every task in the trace.
- **Reproduction Scripts**: After every evaluation run, the harness generates an inert reproduction script in `reports/repro/repro_<id>.txt` containing exact CLI instructions to re-run the scenario.

### `scenario generate`
Interactively workspace to generate new test scenarios via a terminal wizard.
```bash
multiagent-eval scenario generate
```

## Plugin Commands

### `plugin <name> <command>`
Execute plugin-specific subcommands. Plugins register their own commands under a secure namespace to prevent command hijacking.
```bash
multiagent-eval plugin <plugin_name> <command> [options]
```

> **Security Note:** All plugin commands are namespaced under `multiagent-eval plugin <name>` to prevent command hijacking. The legacy `extend_cli` hook has been removed.

