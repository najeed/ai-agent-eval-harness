# AI Agent Evaluation Harness — Comprehensive Guide

> This document is the single authoritative reference for using, extending, and developing the AI Agent Evaluation Harness.
> It is organized into three levels: **Quick Start**, **User Manual**, and **Developer Guide**.

---

## 1) Quick Start (Get Running in Minutes)

### 1.1 Install and Run

1. Clone the repository and install:

```bash
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness
pip install -e .
pip install -r requirements.txt
```

2. (Optional) Run the full lab with Docker:

```bash
docker-compose up -d
```

3. Run a quick evaluation (default industry: `telecom`):

```bash
eval-harness evaluate --path industries/telecom --export
```

4. View results:

- Generated evaluation output lives under `reports/` (JSON, trajectories, heatmaps)
- The dashboard (if running via Docker) is available at: `http://localhost:8501`


### 1.2 Run a Single Scenario

```bash
eval-harness run scenarios/starter_scenario.json
```

### 1.3 Inspect a Saved Run

```bash
eval-harness replay --path runs/run.jsonl
```

---

## 2) User Manual (Detailed Feature Walkthrough)

### 2.1 Core Concepts

- **Scenario**: A JSON file describing an evaluation task (tasks, tools, policies, success criteria, etc.).
- **Task**: A unit of work inside a scenario (e.g., ``task_id``, ``description``, ``success_criteria``).
- **Tool Sandbox**: A simulated runtime that responds to agent tool calls based on mock behaviors defined in the scenario.
- **Agent Adapter**: The code that talks to the agent (HTTP by default, pluggable via `AgentAdapterRegistry`).
- **AES (Agent Eval Specification)**: A YAML/JSON standard that defines benchmark scenarios, tasks, metrics, and policies in a vendor-agnostic format.
- **Metrics**: Scoring components used to rate and validate agent behavior (policy compliance, path parsimony, state verification, etc.).


### 2.2 Running Evaluations (CLI)

#### `evaluate`

This command runs a batch of scenarios.

```bash
eval-harness evaluate --path industries/telecom --format jsonl --output reports/latest_results.json --attempts 3
```

Key arguments:
- `--path`: Path to a file or directory containing scenario(s).
- `--format`: `jsonl` (default) or `csv`.
- `--output`: Output report path.
- `--limit`: Limits number of scenarios run.
- `--attempts`: Run pass@k (multiple attempts per scenario).

During evaluation the harness will:
- Load each scenario
- Run each task in a loop (max turns controlled by `EVAL_MAX_TURNS`)
- Call the agent via HTTP (`AGENT_API_URL`) or a registered adapter
- Execute tool calls in the sandbox and update state
- Score the result via metrics and output reports


#### `run`

Run a single scenario file:

```bash
eval-harness run scenarios/your_scenario.json -k 2
```

This is useful for quick debugging and iterating on a single test case.


#### `replay`

Replays a previously recorded run trace:

```bash
eval-harness replay --path runs/run.jsonl
```

It prints conversation events, agent responses, tool calls/results, and evaluation metrics.


### 2.3 Scenario Structure

A scenario (JSON) typically includes:

- `scenario_id` (string)
- `title` (string)
- `industry` (string)
- `initial_state` (optional dict)
- `agent_topology` (optional dict for multi-agent shared state permissions)

  When specified, `agent_topology` controls which agents can read or write which parts of the shared state.
  Each agent can be defined with `reads` and `writes` lists of JSON-path-like keys.
  This enables multi-agent scenarios where each agent has a scoped view of the shared state and prevents
  unintentional cross-agent state leakage.

  Example:
  ```json
  "agent_topology": {
    "agent_a": {"reads": ["user.*"], "writes": ["user.profile"]},
    "agent_b": {"reads": ["user.*", "order.*"], "writes": ["order.status"]}
  }
  ```

- `policies` (optional dict for policy enforcement)
- `tools` (optional dict defining mock tool behaviors)
- `tasks`: array of task objects

A task object includes:

- `task_id`
- `description` (task prompt)
- `success_criteria` (which metrics to apply and thresholds)
- `required_tools` (optional: tools agent should call)
- `expected_state_changes` (for `state_verification` metric)


### 2.4 Metrics & Scoring

The harness supports a metric registry and applies metrics per task during evaluation.

Common built-in metrics include:
- `policy_compliance` — checks for policy violations in the conversation.
- `path_parsimony` — rewards fewer turns (efficiency).
- `state_verification` — ensures state mutations match expectations.
- `tool_call_correctness` — checks whether the agent used the expected tools.
- `consistency_score` — measures stability across multiple attempts.

The evaluation engine reports both raw scores and a success boolean based on configured thresholds.


### 2.5 Drift & Triage (Advanced Use)

- `import-drift`: Converts production traces into new scenario test cases.
- `triage`: Classifies failures (e.g., `CONNECTION_ERROR`, `POLICY_VIOLATION`).

```bash
eval-harness import-drift --input production_trace.jsonl --industry telecom --output-dir industries/telecom/scenarios
```

---

## 3) Developer Guide (Architecture + CLI + Extensibility)

### 3.1 Project Layout

Key directories:
- `eval_runner/` — Core engine, loaders, metrics, reporter, plugins, simulators, etc.
- `industries/` — Scenario libraries grouped by industry.
- `docs/guides/help/` — User/developer documentation (onboarding + guides).
- `reports/` — Generated evaluation artifacts.
- `runs/` — Recorded run traces (`run.jsonl`).


### 3.2 CLI Overview

The CLI is implemented in `eval_runner/cli.py`.

Key commands:
- `evaluate` — batch scenario evaluation
- `run` — single scenario
- `aes validate` — validate AES benchmark files against schema
- `spec-to-eval` — convert Markdown spec to scenario JSON
- `import-drift` — import production trace into scenarios
- `mutate` — generate adversarial test variants (typos / ambiguity / injection)


### 3.3 Plugin Architecture

Plugins can extend CLI arguments and hook into evaluation lifecycle events.

The core plugin manager exposes hooks:
- `extend_cli` — add CLI arguments
- `before_evaluation` — called before evaluation begins
- `on_turn_end` — called after each agent turn
- `after_evaluation` — called after all attempts finish

Plugins register via `eval_runner/plugins.py` and are discovered via entry points.


### 3.4 Extending the Agent Adapter

The default adapter is HTTP-based and uses `AGENT_API_URL`.

You can add a custom adapter by registering with `AgentAdapterRegistry.register(protocol, func)`.

Example:

```python
from eval_runner.engine import AgentAdapterRegistry

async def my_adapter(payload):
    # Custom logic to call an agent
    return {...}

AgentAdapterRegistry.register("myprotocol", my_adapter)
```

Then invoke it by setting the protocol in evaluation configuration or in a plugin.


### 3.5 Tool Sandbox & Simulators

The sandbox implementation is in `eval_runner/tool_sandbox.py`.

- Tools are defined per scenario under `tools`.
- Policies are defined via `policies` and enforced during tool calls.
- Shared state is handled through `SharedStateRegistry` for multi-agent setups.
- Built-in simulators live under `eval_runner/simulators.py` and can be invoked by tool name prefix.


### 3.6 Metrics & Registry

Metrics are managed by `eval_runner/metrics.py`.

It exposes `MetricRegistry` to register new metric functions.

Metric functions take a criterion and a summary (or task output) and return a numeric score.

To add a new metric:
1. Implement a metric function
2. Register it with `MetricRegistry.register("metric_name", func)`


### 3.7 Tests

Run the full suite with:

```bash
pytest
```

For focused tests, target a module:

```bash
pytest tests/test_engine.py
```

---

## Appendix: Useful Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Endpoint for agent calls |
| `EVAL_MAX_TURNS` | `5` | Max turns per task |

---

For a full deep dive into the AES specification, drift/triage workflows, and industry contribution patterns, read the other documents in `docs/guides/help/`.
