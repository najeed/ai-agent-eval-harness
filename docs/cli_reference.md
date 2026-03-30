# CLI Reference

The `multiagent-eval` (or `python -m eval_runner`) CLI provides a comprehensive suite of tools for agent evaluation, management, and debugging.

## Core Commands

### `evaluate`
Run evaluations on one or more scenarios.
```bash
multiagent-eval evaluate --path <path> [--attempts K] [--limit N] [--verbose]
```
- `--agent`: Unified agent target. Can be a URL (for `http`, `autogen`, `langgraph`), a shell command (for `local`), or an address (for `socket`).
- `--protocol`: Agent protocol (e.g., `http`, `local`, `socket`, `autogen`, `langgraph`, etc.). **Note:** Core protocols are always available; ecosystem adapters are discovery-driven.
- `--agent-cmd`: Shell command to start the agent (required for `local` protocol).
- `--agent-socket`: Socket address (required for `socket` protocol).
- `--agent-name`: Human-readable name for the agent (for reports and leaderboards). Priority: CLI Flag > Zero-Touch Identity > Endpoint URL.
- `--format`: Dataset format (`jsonl` or `csv`).

**Environment Variables (.env Priority):**
| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint for `http` protocol |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `MAX_ENGINE_ATTEMPTS` | `50` | Global engine retry limit |
| `RUN_LOG_DIR` | `runs` | Directory for execution traces |
| `RUN_LOG_PER_RUN` | `true` | Save individual trace files per scenario |
| `RUN_LOG_MASTER` | `true` | Consolidated trace log |
| `JUDGE_PROVIDER` | `ollama` | LLM Judge provider (`openai`, `anthropic`, `gemini`, `ollama`, `grok`) |
| `JUDGE_MODEL` | - | Specific model for the judge (e.g., `llama4`) |
| `LUNA_JUDGE_TEMPERATURE`| `0.0` | Temperature for judge generation |
| `DEFAULT_ADAPTER_TIMEOUT`| `30` | Network timeout for agent adapters |
| `DEFAULT_LLM_TIMEOUT` | `10` | Timeout for LLM provider calls |
| `PLUGIN_TIMEOUT` | `5.0` | Execution timeout for eval plugins |
| `OLLAMA_API_URL` | `.../api/chat` | Ollama model service endpoint |
| `AUTOGEN_API_URL` | `...` | Endpoint for AutoGen protocol |
| `OPENAI_API_KEY` | - | API key for OpenAI provider |
| `ANTHROPIC_API_KEY`| - | API key for Anthropic provider |
| `GOOGLE_API_KEY` | - | API key for Gemini provider |
| `XAI_API_KEY` | - | API key for xAI/Grok provider |
| `ENABLE_DEMO` | `true` | Enable internal UI demo features |


**Research Summary Output:**
When `--attempts` > 1, the harness generates:
- `reports/research_summary.json`: Raw aggregate data.
- `reports/research_summary.md`: A formatted Markdown table of Pass@k, Success Consistency, and Semantic Stability.

### `run`
Execute a single scenario file or a Benchmark URI.
```bash
multiagent-eval run --scenario <path_or_uri> [--attempts K] [--agent-name <name>] [--verbose] [--output <path>]
```
- `--attempts`: Number of attempts for the single scenario.
- `--agent-name`: Human-readable name for reporting.
- `--verbose`: Enable detailed logging.
- `--output`: Save results to a specific JSON file.
- **Example (Benchmark):** `multiagent-eval run --scenario gaia://2023` (Executes all scenarios in the GAIA 2023 benchmark).

### `list`
Search the scenario catalog with keyword and faceted filtering.
```bash
multiagent-eval list [--search <query>] [--refresh]
```
- `--search`: Search scenarios by title, industry, or tags.
- `--refresh`: Rebuild the scenario index from source.

### `catalog-search`
Deep search across indexed scenario metadata.
```bash
multiagent-eval catalog-search --query <term>
```

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
multiagent-eval init --dir <directory_name> --industry <industry_name> [--protocol <p>] [--agent-cmd <cmd>]
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

### `inspect`
Show formatted metadata for a specific scenario file.
```bash
multiagent-eval inspect --scenario-path <path>
```

### `verify`
Verify the integrity of a run trace against an optional manifest.
```bash
multiagent-eval verify --path <run.jsonl> [--manifest <manifest.json>]
```

### `spec-to-eval`
Convert a Markdown PRD/Spec file into a structured Scenario JSON.
```bash
multiagent-eval spec-to-eval --input <prd.md> [--output <scenario.json>]
```
- `--input` (or `--path`): Path to the Markdown specification file.
- `--output`: Optional. Custom output path for the generated JSON (defaults to `scenario.json`).

**Dual-Mode Parsing Logic:**
1. **Deterministic Static Parsing**: The command first attempt to parse the Markdown using regex. It identifies:
    - **Metadata**: Title (H1), Industry, Use Case, and Core Function (via `**Field:**` patterns).
    - **Manual Tasks**: If `###` headers are found within a `## Tasks` section, they are parsed as individual nodes with sequential dependency edges.
    - **Topology & Policies**: Sections defined with `## Topology` and `## Policies` are mapped to the AES metadata.
2. **LLM-Augmented Synthesis**: If no structured tasks are found, the harness triggers an internal LLM (e.g., Gemini) to derive a balanced suite of 3-5 tasks (Positive, Negative, and Adversarial flows) based on the PRD's business rules and tool definitions.

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
**Example:** `multiagent-eval failures search "pii leaks"` discovers and imports realistic failing scenarios from the corpus.

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
multiagent-eval playground [--agent <url>] [--protocol <p>] [--agent-cmd <cmd>] [--agent-name <name>] [--verbose]
```

### `record`
Record a live interaction with an agent and save it as a structured trace.
```bash
multiagent-eval record [--agent <url>] [--protocol <p>] [--agent-cmd <cmd>] [--agent-name <name>] [--verbose]
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

> **Security Note:** All plugin commands are namespaced under `multiagent-eval plugin <name>` to prevent command hijacking. 
