# 🧠 User Manual — AI Agent Evaluation Harness

This guide is for users who want to run and understand evaluations without diving into internal implementation details.

---

## 📌 Table of Contents
1. [Core Concepts](#core-concepts)
2. [Running Evaluations (CLI)](#running-evaluations-cli)
3. [Scenario Structure](#scenario-structure)
4. [Metrics Explained](#metrics-explained)
5. [Drift & Triage (Advanced)](#drift--triage-advanced)

---

## 📚 Core Concepts

### 🗂️ Scenario
A scenario is the unit of evaluation. It's a JSON file that defines:

- `scenario_id` — unique identifier
- `title` — human-friendly name
- `industry` — category for grouping
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
- `state_verification` — validates expected state changes
- `tool_call_correctness` — checks the correct tools were used
- `consistency_score` — checks stability across multiple runs

---

## ▶️ Running Evaluations (CLI)

### 🧪 `evaluate` — batch evaluation

```bash
eval-harness evaluate --path industries/telecom --format jsonl --output reports/latest_results.json --attempts 3
```

**Key options:**
- `--path` (required): Scenario file or directory
- `--format`: `jsonl` (default) or `csv`
- `--output`: Output report path
- `--limit`: Limit number of scenarios executed
- `--attempts`: Run pass@k (multiple attempts per scenario)

**What happens during evaluation:**
1. Loads each scenario
2. Runs each task for up to `EVAL_MAX_TURNS` turns
3. Calls the agent (default: HTTP adapter)
4. Executes sandbox tool calls
5. Computes metrics
6. Writes reports and trace files

### ⚡ CLI Quick Reference

| Command | Common options | What it does |
|---|---|---|
| `eval-harness evaluate` | `--path`, `--format`, `--output`, `--limit`, `--attempts` / `-k` | Run a set of scenarios (batch mode) |
| `eval-harness run` | `-k` | Run a single scenario JSON file |
| `eval-harness replay` | `--path` | Replay a recorded run trace |
| `eval-harness aes validate` | `path` | Validate AES benchmark YAML |
| `eval-harness quickstart` | (none) | Run a 60-second demo (spawns agent + runs eval) |
| `eval-harness doctor` | (none) | Check environment and dependencies |
| `eval-harness report` | `path` | Generate rich HTML report from a run trace |
| `eval-harness scenario generate` | (none) | Interactively bootstrap new scenarios |
| `eval-harness record` | `--agent` | Record real-time interactions into a trace file |
| `eval-harness playground` | `--agent` | Interactive REPL for agent experimentation |
| `eval-harness spec-to-eval` | `--input`, `--output` | Convert Markdown spec to scenario JSON |
| `eval-harness import-drift` | `--input`, `--industry`, `--output-dir` | Convert production trace to scenario |
| `eval-harness mutate` | `--input`, `--type`, `--output` | Generate adversarial scenario variants |

### 🧩 `run` — single scenario

```bash
eval-harness run scenarios/your_scenario.json -k 2
```

Use this for rapid iteration and debugging.

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
Runs a complete evaluation loop using the built-in sample agent.
```bash
eval-harness quickstart
```
It automatically spawns the agent server, runs a troubleshooting scenario, and generates a visual report.

### 🔍 `doctor` — Environment Validator
Troubleshoot your installation and connectivity.
```bash
eval-harness doctor
```

### 🎨 `report` — Visual Reporting
Generate a premium HTML report with interactive trajectory maps.
```bash
eval-harness report runs/run-<id>.jsonl
```

### ✨ `scenario generate` — Interactive Scaffolding
Bootstrap new test cases without writing JSON by hand.
```bash
eval-harness scenario generate
```

### ⏺ `record` — Trace Capture
Capture real interactions with your agent to create new eval scenarios.
```bash
eval-harness record --agent http://localhost:5001/execute_task
```

### 🎮 `playground` — Interactive Experimentation
Talk to your agent directly in the CLI and see how it performs.
```bash
eval-harness playground --agent http://localhost:5001/execute_task
```

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
The harness loads scenarios from `industries/<industry>/scenarios/`.
To add a new industry or scenario:

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
eval-harness run industries/<your_industry>/scenarios/<file>.json
```

4. (Optional) Run an industry batch:

```bash
eval-harness evaluate --path industries/<your_industry>
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

### 🔁 `consistency_score`
Used when `--attempts > 1` to measure stability across runs.

---

## 🧠 Drift & Triage (Advanced)

### 🌪️ 5.1 Importing Drift
Convert production traces into evaluation scenarios:

```bash
eval-harness import-drift --input production_trace.jsonl --industry telecom --output-dir industries/telecom/scenarios
```

### 🧩 5.2 Triage
The harness can categorize failures (e.g., connection errors, policy violations) for easier review.

---

## 📎 Next Steps
For architecture and extension patterns, read the Developer Guide:
- `docs/guides/help/03_DEVELOPER_GUIDE.md`
