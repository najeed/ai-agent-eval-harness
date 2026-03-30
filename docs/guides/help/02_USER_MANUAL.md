# 🧠 User Manual — MultiAgentEval

This guide is for users who want to run and understand evaluations without diving into internal implementation details.

---

## 📌 Table of Contents
1. [Core Concepts](#core-concepts)
2. [Running Evaluations (CLI)](#running-evaluations-cli)
3. [Scenario Structure](#scenario-structure-example)
4. [Metrics Explained](#metrics-explained)
5. [Drift & Triage (Advanced)](#drift-triage-advanced)

---

## 📚 Core Concepts

### 🗂️ Scenario
A scenario is the unit of evaluation. It's a JSON file that defines:

- `scenario_id` — unique identifier
- `title` — human-friendly name
- `industry` — category for grouping
- `dataset` — (optional) path to a synthetic CSV/JSONL dataset to ground the scenario. **Path Decoupling (v1.1+)**: Relative paths (e.g., `./data.csv`) are resolved relative to the scenario file itself.
- `tasks` — list of tasks to run
- `tools` — mock tool behaviors (optional)
- `policies` — rules and governance checks (optional)
- `initial_state` — starting state (optional)

### ✅ Task
A task is a step in a scenario:

- `task_id`
- `description` — the prompt sent to the agent
- `success_criteria` — metrics + thresholds used to determine success
- `required_tools` — which tools the agent should call (optional)
- `expected_state_changes` — expected changes to sandbox state (optional)

### 🧰 Tool Sandbox
The harness uses a sandbox to simulate tool calls and external dependencies. This means:
- No real API calls are made unless explicitly configured
- Tool behavior is controlled by the scenario definition
- Policies can be enforced during tool execution

### 🧩 AES (Agent Eval Specification)
AES is a standardized YAML/JSON schema for defining benchmarks, tasks, expected outcomes, metrics, and policy constraints. It enables consistent sharing of evaluation scenarios across tools and repositories.

### 📏 Metrics
Metrics score an agent’s performance. Built-in metrics include:
- `policy_compliance` — avoids policy violations
- `path_parsimony` — prefers fewer turns (efficiency)
- `state_verification` — validates expected state changes. Supports **dot-notation** (e.g., `user.profile.balance`) for nested object verification.
- `calculation_accuracy` — High-Fidelity: extracts and validates numerical results within a configurable tolerance.
- `planning_quality` — evaluates strategic sequencing and decision-making logic.
- `root_cause_analysis_correctness` — assesses the accuracy of agent diagnostics.
- `consistency_score` — checks stability across multiple runs
- `luna_judge_score` — semantic and behavioral evaluation via LLM-Judge (calibratable to human ground truth, with required provider guards).

---

## ▶️ Running Evaluations (CLI)

### 🧪 `evaluate` — batch evaluation

```bash
multiagent-eval evaluate --path industries/telecom --format jsonl --output reports/latest_results.json --attempts 3
```

**Key options:**
- `--path` (required): Path to scenario file, directory, or remote URI
- `--format`: Input dataset format (`jsonl` or `csv`)
- `--output`: Path to save the final evaluation results JSON
- `--limit`: Limit the total number of scenarios executed during the batch
- `--attempts` / `-k`: Run pass@k (execute multiple attempts per scenario)
- `-f, --force`: Force evaluation by bypassing existing trace/completion checks
- `-v, --verbose`: Enable high-fidelity verbose trace logging to the console
- `--agent`: Specify the target agent endpoint or connection identifier
- `--protocol`: Select communication protocol (`http`, `local`, `socket`, `autogen`, etc.)
- `--seed`: Set a random seed for deterministic evaluation runs
- `--per-run-logs`: Force creation of individual .jsonl traces for every attempt
- `--master-log`: Append all results from the batch into a single `run.jsonl`

**What happens during evaluation:**
1. Loads each scenario
2. Runs each task for up to `EVAL_MAX_TURNS` turns
3. Calls the agent (default: HTTP adapter)
4. Executes sandbox tool calls
5. Computes metrics
6. Writes reports and trace files

### ⚡ CLI Quick Reference

| Command | Common Options | Purpose |
|---|---|---|
| **Core Evaluation** | | |
| `evaluate` | `--path`, `-k`, `-f`, `-v`, `--agent`, `--protocol` | Batch execution of scenarios across a dataset |
| `run` | `--scenario`, `-k`, `-f`, `-v`, `--agent` | Execution of a single specific scenario file |
| `playground` | `--agent`, `--protocol`, `-v` | Interactive REPL for real-time agent experimentation |
| `record` | `--agent`, `--protocol`, `--agent-name` | Capture live interactions into an executable trace |
| `replay` | `--path` | Replay a recorded trace via the Flight Recorder |
| `verify` | `--path`, `--manifest` | Verify cryptographic integrity of a run trace |
| `quickstart` | (none) | 60-second engine demonstration (spawns agent + eval) |
| **Specifications** | | |
| `aes validate` | `--path` | Validate a scenario against AES JSON schema |
| `aes add-standard`| `--id`, `--industry`, `--description` | Register a new industry standard to local manifest |
| **Scenario Management** | | |
| `inspect` | `--scenario-path` | Display task breakdown and architecture for a scenario |
| `lint` | `--path` | Score scenario for AES compliance and quality |
| `list` | `--search`, `--refresh` | Search and explore the local industry registry |
| `catalog-search` | `--query` | Search global and local scenario catalogs |
| `mutate` | `--input`, `--type`, `-f` | Generate adversarial/edge-case scenario variants |
| `spec-to-eval` | `--input`, `--output` | Convert Markdown PRD/Spec to Scenario JSON |
| **Analysis & Reporting** | | |
| `calibrate` | `--path`, `--plot` | Measure judge agreement against human labels |
| `explain` | `--path` | Diagnose root causes from evaluation traces |
| `leaderboard` | `--dir`, `--output` | Generate performance rankings from run traces |
| `list-metrics` | (none) | Display all registered evaluation metrics |
| `report` | `--path`, `--share` | Generate stylized HTML reports from run traces |
| `taxonomy` | (none) | Display the official AEH failure taxonomy |
| **Environment** | | |
| `init` | `--dir`, `--industry`, `--registry` | Scaffold a new benchmark environment |
| `doctor` | (none) | Audit local environment and dependencies |
| `cleanup-runs` | `--days`, `-f` | Prune old traces and rotate log artifacts |
| `export` | `--input`, `--output` | Export traces to HF, CSV, or custom formats |
| `install` | `pack_name` | Install curated industrial scenario packs |
| `plugin` | `list`, `register <path>` | Manage external and built-in plugins |
| `registry` | `sync`, `add --url` | Synchronize industry scenario registries |
| `ci generate` | (none) | Generate GitHub Actions workflows for the environment |

### 🧩 `run` — single scenario

```bash
multiagent-eval run --scenario scenarios/your_scenario.json -k 2 -f -v
```

Use this for rapid iteration and debugging. It supports the same core execution flags as `evaluate` (e.g., `--agent`, `--protocol`, `--seed`).

#### 📽️ Run Trace Management

The harness records every event (agent messages, tool calls, metrics) into trace files for debugging and auditing.

**Default Behavior:**
- All runs are appended to `runs/run.jsonl`.
- Each run is also saved to its own file: `runs/run-<run_id>.jsonl`.

**Configuration (Environment Variables):**
| Variable | Default | Description |
|---|---|---|
| `RUN_LOG_DIR` | `runs` | Directory where trace files are stored. |
| `RUN_LOG_PER_RUN` | `true` | Save each run to a separate file. |
| `RUN_LOG_MASTER` | `true` | Append all runs to a master `run.jsonl`. |
| `RUN_LOG_ROTATE_COUNT` | `0` | Number of per-run files to keep. `0` means keep all. |

---

## 🚀 Adoption & Productivity Utilities

These utilities are designed to get you from "installation" to "first eval" in seconds.

### 🏃 `quickstart` — The 60-Second Demo
Runs a complete evaluation loop using the built-in sample agent in your terminal.
```bash
multiagent-eval quickstart
```
*   Spawns the sample agent server process.
*   Runs a telecom troubleshooting scenario.
*   Generates a **Premium HTML report** (Mermaid trajectories enabled) in `reports/`.
*   **Note:** This command is designed for CLI-only instant feedback; use `multiagent-eval console` for the visual experience.

### 🖥️ `console` — React Visual Debugger GUI
Launch a high-fidelity visual dashboard to run scenarios, inspect trace lines chronologically, and review system documentation locally.

#### Key Features:
- **Scenario Explorer**: Browse the catalog with search filters. View real-time **Lint Scores** and quality status badges.
- **Background Execution**: Trigger evaluations directly from the UI; monitor progress in real-time.
- **Visual DNA Debugger**: Live trajectory playback, state inspection, and trace export via the `DebuggerStateStore` hook.
- **API Reference**: Integrated technical documentation drawer for one-click access to guides.

```bash
multiagent-eval console --port 5000
```

### 🔍 `doctor` — Environment Validator
Troubleshoot your installation and connectivity.
```bash
multiagent-eval doctor
```

### 🎨 `report` — Premium Visual Reporting
Generate a premium HTML report with interactive trajectory maps reconstructed from historical trace events.
```bash
multiagent-eval report --path runs/run_<id>.jsonl
```

### ✨ `scenario generate` — Interactive Scaffolding
Bootstrap new test cases without writing JSON by hand.
```bash
multiagent-eval scenario generate
```

### ⏺ `record` — Trace Capture
Capture real interactions with your agent to create new eval scenarios.
```bash
multiagent-eval record --agent http://localhost:5001/execute_task
```

### 🎮 `playground` — Interactive Experimentation
Talk to your agent directly in the CLI and see how it performs.
```bash
multiagent-eval playground --agent http://localhost:5001/execute_task
```

### 🔍 `list` — Scenario Catalog Search
Discover scenarios across the built-in and downloaded libraries.
```bash
multiagent-eval list --search "telecom"
```

### 🧹 `lint` — Quality Scoring
Check your scenarios for AES compliance and technical quality.
```bash
multiagent-eval lint --path industries/telecom/scenarios/troubleshooting_v1.json
```
- **90-100**: High quality, CI-ready.
- **70-89**: Warning (Missing metadata or low complexity).
- **<70**: Fail (Structural errors or zero tasks).

---

## 🚀 Advanced CLI Utilities & UX

### 📦 `install` — Scenario Packs
Rapidly deploy industry-specific scenario bundles (e.g., `telecom-pack`, `rag-agent-pack`).
```bash
multiagent-eval install telecom-pack
```

### 🔬 `analyze` — Repo Scanning
Scan agent repositories to identify tool patterns and auto-generate matching AES scenarios.
```bash
multiagent-eval analyze https://github.com/example/agent
```

### 🤖 `explain` — Trace Analysis
Automated diagnostic analysis of `run.jsonl` traces to identify root causes of agent failures.
```bash
multiagent-eval explain --path runs/run.jsonl
```

### 🛠️ Visual Scenario Editor
Built into the Visual Debugger (`multiagent-eval console`), this tool provides a visual interface for constructing complex AES logic and saving it directly to the local industry catalog.

---

---

## 🧩 Scenario Structure (Example)

```json
{
  "scenario_id": "example_01",
  "title": "Basic instruction",
  "industry": "generic",
  "tasks": [
    {
      "task_id": "t1",
      "description": "Write a friendly greeting.",
      "success_criteria": [
        {"metric": "policy_compliance", "threshold": 1.0},
        {"metric": "path_parsimony", "threshold": 0.5}
      ]
    }
  ]
}
```

## 🧱 Adding Industries & Scenarios
The simplest way to add a completely new industry is to generate a bootstrapped setup using `init`, which automatically creates a starter scenario and linked synthetic datasets.

```bash
multiagent-eval init --dir industries/my_industry --industry my_industry
```

If you prefer to add them manually:
The harness loads scenarios from `industries/<industry>/scenarios/`.

1. Create a directory for your industry (if it doesn't exist):

```bash
mkdir -p industries/<your_industry>/scenarios
```

2. Add a JSON scenario file (any name ending in `.json`):

```json
{
  "scenario_id": "my_scenario_01",
  "title": "Example scenario",
  "industry": "<your_industry>",
  "tasks": [ ... ]
}
```

3. Run it via CLI:

```bash
multiagent-eval run --scenario industries/<your_industry>/scenarios/<file>.json
```

4. (Optional) Run an industry batch:

```bash
multiagent-eval evaluate --path industries/<your_industry>
```

### 🔎 Tip
Keep `scenario_id` unique within the industry and prefer descriptive file names like `scenario_<short-name>.json`.

### 🧩 Agent Topology (Multi-Agent Scenarios)
When a scenario involves more than one agent, you can define an `agent_topology` object to control which agents can read or write which parts of the shared state.
This prevents agents from unintentionally interfering with each other and enables fine-grained multi-agent evaluation.

Example:
```json
"agent_topology": {
  "agent_a": {"reads": ["user.*"], "writes": ["user.profile"]},
  "agent_b": {"reads": ["user.*", "order.*"], "writes": ["order.status"]}
}
```

### ✅ Best practices (Agent Topology)
- **Use topology only when you need multi-agent separation.** For single-agent scenarios, omitting `agent_topology` keeps things simpler.
- **Start with broad read permissions and tighten over time.** This helps avoid accidental “permission denied” failures while you iterate.
- **Match topology to tool behavior.** If a tool writes a state path, ensure the calling agent has `writes` rights for that path.
- **Avoid overlap for sensitive state.** If two agents shouldn’t see each other’s data, keep their `reads` sets disjoint.

### 🛠 Tool Definitions
Tools are defined within the scenario and can:
- Apply state changes
- Return structured outputs
- Enforce policies

Example:

```json
"tools": {
  "send_email": {
    "state_changes": [
      {"path": "emails.sent", "value": true}
    ],
    "output": {"status": "success", "message": "Email sent"}
  }
}
```

### 🚨 Policies
Policies enforce guardrails during tool execution.

Example:

```json
"policies": {
  "withdraw_money": {"max_limit": 500}
}
```

If the agent calls `withdraw_money` with an amount above the limit, the harness returns a `policy_violation` response.

---

## 📊 Metrics Explained

Metrics are evaluated per task and decide if the task succeeded.

### ✅ `policy_compliance`
Ensures the agent didn’t trigger policy violations via tool calls.

### 🧭 `path_parsimony`
Rewards fewer turns (more concise/efficient behavior).

### 🧱 `state_verification`
Validates that the sandbox state matches expected changes.

### 🧰 `tool_call_correctness`
Ensures the agent called required tools.

### 📐 `calculation_accuracy`
High-Fidelity: Uses regex to extract numerical values from the agent's summary and compares them against the expected values with a 0.01 tolerance.

### 🧠 `planning_quality` & `root_cause_analysis`
Advanced cognitive metrics using domain-specific LLM rubrics to evaluate the quality of an agent's planning and diagnostic accuracy.

### 🔁 `consistency_score`
Used when `--attempts > 1` to measure stability across runs.

---

## 🧠 Drift & Triage (Advanced)

### 🌪️ 5.1 Importing Drift
Convert production traces into evaluation scenarios:

```bash
multiagent-eval import-drift --input production_trace.jsonl --industry telecom --output-dir industries/telecom/scenarios
```

### 🔬 5.2 State-Level Trajectory Triage (How Root Cause Isolation Works)
AgentEval isolates the root cause of a failure by combining three layers of analysis — not just scanning logs.

**Layer 1: State Parity Check (VFS Delta)**
Every World Shim (Database, Jira, Git, API, etc.) is "VFS-aware". When an agent calls a tool, AgentEval compares the resulting system state against the "Ground Truth" defined in the scenario. If the agent queries the wrong table or fails to commit a file, the State Divergence is flagged immediately as the **"Patient Zero"** step. This catches "silent failures" where the agent *thinks* it succeeded but the environment changed incorrectly.

**Layer 2: Heuristic Triage Engine (`triage.py`)**
A specialized engine scans the entire trace for failure patterns:
- **Stall Detection** — identifies if an agent is looping (e.g., calling `list_dir` 3 times with no change in behavior).
- **Tool-Level Exceptions** — captures internal simulator errors (e.g., a "404 Not Found" from the API Shim) that the agent might have ignored.
- **Policy Violations** — if a Security Shim blocks an action (like a regex-based data leak), the triage engine flags the exact guardrail triggered.

**Layer 3: Visual Timeline Mapping**
The Visual Debugger's **"Isolate Root Cause"** automatically scrolls the timeline to the first Non-Success Signal — the exact failing node, highlighted in red.

| Layer | What it detects | Why it matters |
| :--- | :--- | :--- |
| **State** | Data/File divergence | Catches silent failures where the agent thinks it succeeded. |
| **Logic** | Loops & Stalls | Identifies when an agent's reasoning has hit a dead-end. |
| **Security** | Policy Violations | Pinpoints exactly which guardrail was triggered and why. |

By combining these layers, AgentEval can distinguish between an agent that *hallucinated a tool's existence* vs. an agent that *used the right tool but with the wrong parameters*.

> **Why use Shims instead of Real APIs?**
> - **Safety**: No risk of accidentally deleting a production database or emailing a real customer.
> - **Determinism**: You can force the shim to fail (e.g., simulate a 500 error) to test error handling.
> - **Speed**: Simulated responses are near-instant vs. real network latency.

📖 See the full technical deep-dive: [`06_TRIAGE_ENGINE_AND_VFS.md`](06_TRIAGE_ENGINE_AND_VFS.md)

---

## 📎 Next Steps
For architecture and extension patterns, read the Developer Guide:
- `docs/guides/help/03_DEVELOPER_GUIDE.md`
- `docs/guides/help/06_TRIAGE_ENGINE_AND_VFS.md`
