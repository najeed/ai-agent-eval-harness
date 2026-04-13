# CLI Reference

The `agentv` (or `python -m eval_runner`) CLI provides a comprehensive suite of tools for agent evaluation, management, and debugging.

## Core Commands

### `evaluate`
Run evaluations on one or more scenarios.
```bash
agentv evaluate --run-id <id><dataset_path> [--attempts K] [--limit N] [--verbose]
```
- `--agent`: Unified agent target. Can be a URL (for `http`, `autogen`, `langgraph`), a shell command (for `local`), or an address (for `socket`).
- `--protocol`: Communication protocol for the agent (`http`, `local`, `socket`, `autogen`, `crewai`, etc.).
- `--agent-cmd`: Local agent executable command (required for `local` protocol).
- `--agent-socket`: Socket address (required for `socket` protocol).
- `--agent-name`: Human-readable name for the agent (for reports and leaderboards). Priority: CLI Flag > Zero-Touch Identity > Endpoint URL.
- `--format`: Dataset format (`jsonl` or `csv`).
- `--seed`: Random seed for deterministic evaluation. Ensures reproducibility of agent trajectories and judge scores.

**Environment Variables (.env Priority):**
| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint for `http` protocol |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `MAX_ENGINE_ATTEMPTS` | `50` | Global engine retry limit |
| `RUN_LOG_DIR` | `runs` | Directory for execution traces |
| `RUN_LOG_PER_RUN` | `true` | Create nested vault directories (Industrial Standard). Set `false` for debugging. |
| `RUN_LOG_MASTER` | `true` | Consolidated trace log (Master Fallback) |
| `JUDGE_PROVIDER` | `ollama` | LLM Judge provider (`openai`, `anthropic`, `gemini`, `ollama`, `grok`) |
| `JUDGE_MODEL` | `llama3` | Specific model for the judge (Industrial Default) |
| `LUNA_JUDGE_TEMPERATURE`| `0.0` | Temperature for judge generation |
| `DEFAULT_ADAPTER_TIMEOUT`| `30` | Network timeout for agent adapters |
| `DEFAULT_LLM_TIMEOUT` | `10` | Timeout for LLM provider calls |
| `PLUGIN_TIMEOUT` | `5.0` | Execution timeout for eval plugins |
| `GOOGLE_API_KEY` | - | API key for Gemini provider |
| `AEH_STRICT_JAIL` | `0` | Set to `1` for project-only path isolation |
| `ENABLE_DEMO` | `true` | Enable internal UI demo features |


**Research Summary Output:**
When `--attempts` > 1, the harness generates:
- `reports/research_summary.json`: Raw aggregate data.
- `reports/research_summary.md`: A formatted Markdown table of Pass@k, Success Consistency, and Semantic Stability.

### `run`
Execute a single scenario file or a Benchmark URI.
```bash
agentv run --scenario <path_or_uri> [--attempts K] [--agent-name <name>] [--verbose] [--output <path>]
```
- `--attempts`: Number of attempts for the single scenario.
- `--agent-name`: Human-readable name for reporting.
- `--verbose`: Enable detailed logging.
- `--output`: Save results to a specific JSON file.
- `--seed`: Random seed for deterministic evaluation.
- `--protocol`: Communication protocol override.
- **Example (Benchmark):** `agentv run --scenario gaia://2023` (Executes all scenarios in the GAIA 2023 benchmark).

### `list`
Search the scenario catalog with keyword and faceted filtering.
```bash
agentv list [--search <query>] [--refresh]
```
- `--search`: Search scenarios by title, industry, or tags.
- `--refresh`: Rebuild the scenario index from source.

### `catalog-search`
Deep search across indexed scenario metadata.
```bash
agentv catalog-search --query <term>
```

### `lint`
Verify scenario quality and AES specification compliance.
```bash
agentv lint --run-id <id><path_to_scenario_or_dir>
```
- Runs automated checks for metadata quality, valid structure, and duplicate detection.
- Provides a quality score (0-100) and detailed warning/error report.

### `init`
Scaffold a new benchmark directory with starter scenarios for a specific industry. Automatically links the scenario to realistic synthetic CSV datasets.
```bash
agentv init --dir <directory_name> --industry <industry_name> [--protocol <p>] [--agent-cmd <cmd>]
```

### `install`
Install curated scenario packs (e.g., `telecom-pack`, `rag-agent-pack`).
```bash
agentv install <pack-name>
```
**Example:** `agentv install telecom-pack` downloads and registers a bundle of 100+ telecom-specific agent scenarios.

### `analyze`
Scan an agent's GitHub repository to identify tool patterns and auto-generate matching AES scenarios.
```bash
agentv analyze <github_url>
```
**Example:** `agentv analyze https://github.com/my-org/my-agent` scaffolds scenarios in `scenarios/auto/` based on detected tool definitions.

## Specification & Validation

### `aes validate`
Validate Agent Eval Specification (.aes.yaml) files against the official schema.
```bash
agentv aes validate --run-id <id><path>
```
- Performs deep structure checking using `jsonschema`.
- Ensures all mandatory benchmark fields are present.

### `inspect`
Show formatted metadata for a specific scenario file.
```bash
agentv inspect --scenario-path <path>
```

### `verify`
Verify the integrity of a run trace using autonomous artifact resolution.
```bash
agentv verify --run-id <run_id>
```
- `--run-id`: [SSOT] Mandatory identifier for the evaluation run. The harness automatically locates the trace and its sidecar manifest in the `runs/` vault.

### `certify`
Generate a Verification Certificate (VC) v3.0.0 for a trace run.
```bash
agentv certify --run-id <id> [--identity system_id] [--status {pass,fail,warning}] [--score 1.0]
```
- `--run-id`: [SSOT] Mandatory identifier for the evaluation run.
- `--identity`: (Optional) Identity ID to use for signing. Defaults to `system_id`.
- `--status`: (Optional) Compliance status to embed.
- `--score`: (Optional) Compliance score (0.0-1.0).
- `--policy-ref`: (Optional) Reference to the policy being certified against.
- `--ttl`: (Optional) Governance TTL in days.

### `gate`
Enforce cryptographic integrity and trace success as a "Hard Gate" in CI/CD pipelines. Returns exit code `0` on success, `1` on failure.
```bash
agentv gate --run-id <id> [--hash <commit_hash>] [--verify-ledger]
```
- `--run-id`: [SSOT] Mandatory identifier for the evaluation run. Automatically resolves the manifest from the vault.
- `--hash`: (Optional) Expected Git commit hash to verify against the trace's metadata.
- `--verify-ledger`: (Optional) Perform full forensic hash check of all sidecar artifacts.
- **Validation**: Enforces SHA-256 binary integrity, **Identity Registry** signature validation, and Forensic Ledger consistency.

### `spec-to-eval`
Convert a Markdown PRD/Spec file into a structured Scenario JSON.
```bash
agentv spec-to-eval --input <prd.md> [--output <scenario.json>]
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
agentv auto-translate --input <document.pdf> --model <model_name> --industry <industry>
```
**Requirement:** `Ollama` must be running locally.

### `ci generate`
Scaffold a `.github/workflows/agent_eval.yml` file to run evaluations automatically on Pull Requests.
```bash
agentv ci generate
```

## Drift & Research

### `import-drift`
Convert production traces (interaction logs) into reusable evaluation scenarios.
```bash
agentv import-drift --input <trace.json> --industry <industry>
```

### `mutate`
Generate adversarial variants of a scenario (e.g., adding typos, prompt injection).
```bash
agentv mutate --input <scenario.json> --type <mutation_type>
```

### `export`
Convert internal execution traces (`run.jsonl`) into externally shareable dataset formats (like HuggingFace Datasets).
```bash
agentv export --input <run.jsonl> --format hf --output <dataset.json>
```

### `failures search`
Query the global Failure Corpus to retrieve known failing edge cases for specific topics (e.g., PII, timeouts).
```bash
agentv failures search <query>
```
**Example:** `agentv failures search "pii leaks"` discovers and imports realistic failing scenarios from the corpus.

### `list-metrics`
Display descriptions for all registered evaluation metrics.

### `list-plugins`
Display all active and persistently registered plugins (Alias for `agentv plugin list`).

## Debugging & Exploration

### `replay`
Replay a previously recorded run trace (Flight Recorder).
```bash
agentv replay --run-id <id>
```
- `--run-id`: [SSOT] Mandatory identifier for the evaluation run.

### `explain`
Automatically analyze a run trace to diagnose root causes with high-fidelity tiered scoring and actionable technical fixes.
```bash
agentv explain --run-id <id>
```
**Forensic Features:**
- **Tiered Confidence Scoring**: Distinguishes between explicit policy violations (100%), induced system/tool errors (85%), and heuristic fallbacks (50%).
- **Identity-Aware Diagnostic**: Anchors failure to the authoritative PBAC Identity Node (`agent_id`, `system_id`) using the **Robust Step-Back Scan**.
- **Actionable Recommendations**: Provides targeted remediation advice (e.g., prompt refinement, tool sandbox optimization) based on the identified failure pattern.
- **Root-Cause Anchoring**: Pinpoints the exact turn index in the trajectory where logic diverged, even if the manifestation happened turns later.

### `calibrate`
Measure alignment between the LLM judge and human ground truth in a flight recorder log.
```bash
agentv calibrate --run-id <id> [--golden <path>] [--plot]
```
**Metrics:** Calculates Pearson Correlation and Mean Absolute Error (MAE) based on paired `luna_judge_score` and `human_score` events.

### `playground`
Launch an interactive REPL to talk to an agent directly in the terminal.
```bash
agentv playground [--agent <url>] [--protocol <p>] [--agent-cmd <cmd>] [--agent-name <name>] [--verbose]
```

### `record`
Record a live interaction with an agent and save it as a structured trace.
```bash
agentv record [--agent <url>] [--protocol <p>] [--agent-cmd <cmd>] [--agent-name <name>] [--verbose]
```

## Utilities

### `console`
Launch the Visual Debugger backend API and Unified React SPA. The debugger provides a high-density dashboard for end-to-end evaluation management:
- **Scenario Explorer**: Browse the catalog with faceted filters, global search, and real-time **Lint Scores**.
- **Visual AES Builder**: Drag-and-drop integrated logic builder that saves production-ready JSON directly to the industry catalog.
- **Background Evaluation**: Trigger runs directly from the UI; the console handles background execution and event streaming.
- **Visual Debugger**: Real-time trajectory playback with interactive state inspection powered by the `DebuggerStateStore`.
```bash
agentv console [--host 127.0.0.1] [--port 5000]
```

### `doctor`
Check the local environment for missing dependencies or configuration issues.
```bash
agentv doctor
```

### `quickstart`
Run a 60-second guided demo that spawns a mock agent and executes an evaluation.
```bash
agentv quickstart
```

### `report`
Generate a standalone Premium HTML report from an execution trace.
```bash
agentv report --run-id <id> [--share]
```
**Feature Highlights:**
- **Trace Reconstruction**: Automatically reconstructs hierarchical task results, metrics, and triage tags from historical JSONL events.
- **Visual Trajectories**: Generates interactive Mermaid maps for every task in the trace.
- **Reproduction Scripts**: After every evaluation run, the harness generates an inert reproduction script in `reports/repro/repro_<id>.txt` containing exact CLI instructions to re-run the scenario.

### `scenario generate`
Interactively workspace to generate new test scenarios via a terminal wizard.
```bash
agentv scenario generate
```

## Plugin Management

### `plugin register`
Register an external plugin persistently in the local registry.
```bash
agentv plugin register <path_to_plugin>
```
- `<path_to_plugin>`: File system path or Python module path to register.
- Automatically normalizes the registration into the required split `module`/`class` schema.

### `plugin unregister`
Remove a plugin from the persistent registry.
```bash
agentv plugin unregister <plugin_name_or_id>
```

### `plugin list` (Alias: `list-plugins`)
List all active and persistently registered plugins.
```bash
agentv plugin list
# OR
agentv list-plugins
```

### `plugin <name> <command>`
Execute plugin-specific subcommands. Plugins register their own commands under a secure namespace to prevent command hijacking.
```bash
agentv plugin <plugin_name> <command> [options]
```

> **Security Note:** All plugin commands are namespaced under `agentv plugin <name>` to prevent command hijacking. 
