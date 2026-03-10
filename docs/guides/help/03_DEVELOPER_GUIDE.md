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

### Common CLI options
- `--attempts`: Produce pass@k results by running multiple tries per scenario (supported by `evaluate`, and by `run` via `-k`).
- `--limit`: Run a subset of scenarios (useful for quick iterations).

### Plugin hook: `extend_cli`
Plugins can add arguments and options to commands. This is the primary extensibility point for CLI behavior.

---

## 🧠 3) Evaluation Engine

Core evaluation flow is implemented in `eval_runner/engine.py`.

### 🛠 Architecture (high level)
1. Load scenario JSON
2. Create `EvaluationContext`
3. Emit `run_start` event (writes to `runs/run.jsonl`)
4. For each task:
   - Run up to `EVAL_MAX_TURNS` turns
   - Call agent via `AgentAdapterRegistry`
   - Execute tool calls via `ToolSandbox`
   - Record conversation history and tool outputs
   - Score with metrics
5. Aggregate multi-attempt results (pass@k, consistency)
6. Emit `run_end`

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
- `extend_cli` — Add CLI args
- `before_evaluation` — Run before each evaluation begins
- `on_turn_end` — Called after each agent turn
- `after_evaluation` — Run after evaluation completes

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

For reference, see other documentation in `docs/guides/help/`.
