# 🛠 Developer Guide — AI Agent Evaluation Harness

This guide is for engineers building on or extending the harness.

---

## 📂 1) Repository Overview

**Key directories:**
- `eval_runner/` — Core engine, loaders, metrics, reporter, plugins, simulators, CLI
- `industries/` — Industry scenario libraries
- `reports/` — Generated evaluation artifacts (JSON, trajectories, heatmaps)
- `runs/` — Recorded execution traces (`run.jsonl`)
- `docs/guides/help/` — Documentation for users and contributors
- `tests/` — Unit & integration tests

> 📌 Tip: Most contributions start by editing a scenario in `industries/` and running it via the CLI.

---

## 🧩 2) CLI Architecture

Entry point: `eval_runner/cli.py`

### Main commands
- `evaluate` — Run a batch of scenarios
- `run` — Run a single scenario
- `replay` — Replay a run trace
- `aes validate` — Validate AES benchmark definitions (AES = Agent Eval Specification; a standardized YAML/JSON benchmark format)
- `spec-to-eval` — Convert Markdown specs into JSON scenarios
- `import-drift` — Convert production traces into scenarios
- `mutate` — Generate adversarial variants (typos, ambiguity, injection)
- `doctor` — Validate environment health and dependencies
- `quickstart` — End-to-end evaluation demo using `sample_agent`
- `report` — Re-generate rich HTML reports from existing `.jsonl` traces
- `scenario generate` — Interactive generator for boilerplate scenarios
- `record` — Real-time agent interaction logger
- `playground` — Interactive CLI REPL for agent testing

### Common CLI options
- `--attempts`: Produce pass@k results by running multiple tries per scenario (supported by `evaluate`, and by `run` via `-k`).
- `--limit`: Run a subset of scenarios (useful for quick iterations).

### Plugin hook: `extend_cli`
Plugins can add arguments and options to commands. This is the primary extensibility point for CLI behavior.

---

## 🧠 3) Evaluation Engine

Core evaluation flow is implemented in `eval_runner/engine.py`.

### 🛠 Architecture (Zero-Touch Core)
The engine is now a decoupled orchestration layer:
1. **Runner (`runner.py`)**: Orchestrates the high-level evaluation loop, handling multi-attempt (`pass@k`) logic.
2. **SessionManager (`session.py`)**: Manages individual evaluation attempts, conversation trajectories, and tool execution.
3. **EventEmitter (`events.py`)**: A centralized bus that emits state transitions. Plugins subscribe to this bus for "Flight Recording" without engine modifications.
4. **Plugins (`plugins.py`)**: Enhanced with interception capabilities (`on_tool_request`) and specific turn lifecycle hooks.

#### High-Level Flow:
1. `run_evaluation` (in `engine.py`) initializes specialized internal plugins (`FlightRecorderPlugin`, `ReportingPlugin`).
2. `DefaultRunner.run()` initializes the `EvaluationContext`.
3. `SessionManager` executes tasks and turns:
   - `on_agent_turn_start` hook.
   - Call agent via `AgentAdapterRegistry`.
   - `on_turn_end` hook.
   - Tool execution with `on_tool_request` interception.
4. `EventEmitter` automatically signals `RUN_START`, `TASK_START`, `TURN_START`, `TOOL_CALL`, `TOOL_RESULT`, etc.
5. Metrics are calculated within the session but emitted as events.

### 🕯️ Run Logging & Rotation
The engine supports configurable logging via environment variables:
- `RUN_LOG_DIR`: Directory for traces (default: `runs`)
- `RUN_LOG_PER_RUN`: Save individual run files (default: `true`)
- `RUN_LOG_MASTER`: Append to master `run.jsonl` (default: `true`)
- `RUN_LOG_ROTATE_COUNT`: Max number of per-run files to keep (default: `0` / infinite)

### 🔌 Agent Adapter
Default: HTTP POST to `AGENT_API_URL`

You can add custom adapters:

```python
from eval_runner.engine import AgentAdapterRegistry

async def custom_adapter(payload):
    # Custom logic for calling an agent
    return {"action": "final_answer", "content": "ok"}

AgentAdapterRegistry.register("custom", custom_adapter)
```

> ⚠️ Note: The harness uses the registered adapter by protocol name. The default protocol is `http`.

---

## 🧩 4) Plugin System

Plugins hook into the evaluation lifecycle via `plugins.manager.trigger(...)`.

### Standard hooks
- `extend_cli` — Add CLI args (automated via `register_arguments`)
- `before_evaluation` — Run before each evaluation begins
- `on_agent_turn_start` — Called before an agent turn begins [NEW]
- `on_turn_end` — Called after each agent turn
- `on_tool_request` — Intercept and potentially block tool calls [NEW/CRITICAL]
- `on_tool_result` — Monitor state side-effects [NEW]
- `on_error` — Handle exceptions [NEW]
- `on_metrics_calculated` — Access results before aggregation [NEW]
- `after_evaluation` — Run after evaluation completes (used for reporting)

Plugins are discovered via **entry points** configured in `pyproject.toml`.

> 📌 Tip: Add logging, metrics, or custom adapter wiring via `before_evaluation`.

---

## 🧰 5) Tool Sandbox & Simulators

Implementation: `eval_runner/tool_sandbox.py`

### 5.1 Tool Definitions
Tools are declared in scenarios under the `tools` key. Each tool can:
- Mutate sandbox state (`state_changes`)
- Return structured output (`output`)
- Trigger policy checks

### 5.2 Policies
Policies are defined under `policies` in the scenario.
A tool call that violates a policy returns:

```json
{"status": "policy_violation", "violation": "..."}
```

### 5.3 Shared State (Multi-Agent)
`SharedStateRegistry` provides permissioned read/write access controlled by `agent_topology`.

#### Best practices (Agent Topology)
- Only use `agent_topology` when you need multiple agents in one scenario; single-agent scenarios can omit it.
- Ensure the topology aligns with your tools: if a tool modifies a path, the agent invoking it must have `writes` permission for that path.
- Use conservative defaults (e.g., `reads: ["*"]`) while iterating, then lock down permissions once behavior is stable.
- Treat shared state as “contracted” data: keep sensitive state in isolated paths to avoid accidental cross-agent access.

### 5.4 Simulators
Built-in simulators live in `eval_runner/simulators.py`. They activate when a tool name matches `<sim_name>_*`.

---

## 📊 6) Metrics System

Metrics are managed via `eval_runner/metrics.py` using `MetricRegistry`.

### ✅ Adding a Metric
1. Implement a metric function (sync or async)
2. Register it:

```python
from eval_runner.metrics import MetricRegistry

def my_metric(criterion, summary):
    return 1.0 if "success" in summary.lower() else 0.0

MetricRegistry.register("my_metric", my_metric)
```

3. Use it in `success_criteria` of your scenario:

```json
{"metric": "my_metric", "threshold": 1.0}
```

> 💡 Tip: Use `summary` to access the last agent response (commonly contains a `summary` field).

---

## 🧪 7) Scenario Development Workflow

1. Create or update a scenario JSON in `industries/<industry>/scenarios/`.
2. Run it via CLI:

```bash
eval-harness run industries/<industry>/scenarios/<scenario>.json
```

3. Inspect results in `reports/` or replay the run trace.

---

## 🧪 8) Testing

Run all tests:

```bash
pytest
```

Run targeted tests:

```bash
pytest tests/test_engine.py
```

---

## 🤝 9) Contribution & Extending

- Add new industries or scenarios under `industries/`.
- Add metrics by registering them in `eval_runner/metrics.py`.
- Add simulators via `eval_runner/simulators.py`.
- Extend CLI via plugin hooks.

---

## 🧪 10) Productivity Utilities (Internal Logic)

### 10.1 `doctor.py`
Uses `aiohttp` to probe agent availability and `subprocess`/`sys` to audit the local environment.

### 10.2 `quickstart.py`
Lifecycle manager that:
1. Spawns `sample_agent/agent_app.py` as a subprocess.
2. Invokes `engine.run_evaluation` via Python API.
3. Triggers `reporter.generate_html_report`.
4. Ensures clean process termination across platforms.

### 10.3 `trace_recorder.py` & `playground.py`
These utilities provide lightweight interactive wrappers around agent communication. `record` focuses on generating valid execution events for future replaying or scenario extraction.

---

## 🛰 11) Event-Driven Architecture (Flight Recorder)

The harness uses an `EventEmitter` to enable "Zero-Touch" observable core logic.

### 11.1 EventEmitter Bus
Located in `eval_runner/events.py`. It allows any component (Core or Plugin) to emit a `CoreEvent`.

### 11.2 FlightRecorderPlugin
A built-in plugin (`eval_runner/flight_recorder.py`) that subscribes to all core events. It handles the writing of `.jsonl` traces, moving this responsibility entirely out of the orchestration loop.

---

For reference, see other documentation in `docs/guides/help/`.
