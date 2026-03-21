# 📦 API Reference: Core Evaluator

The `eval_runner` core provides the main orchestration logic for agentic evaluations. It is built on a Zero-Touch architecture that uses dynamic registries and plugin hooks for extensibility.

---

## 🚀 Core Engine API

### `engine.run_evaluation`
Executes a single evaluation scenario. This is the primary entry point for the harness.

**Signature:**
```python
async def run_evaluation(
    scenario: dict, 
    attempts: int = 1, 
    metadata: Optional[dict] = None
) -> Union[dict, list]
```

**Parameters:**
- `scenario`: The Scenario dictionary (loaded via `loader.load_scenario`).
- `attempts`: Number of attempts (K) for `pass@k` scoring.
- `metadata`: Optional dictionary of run-level metadata (e.g., job ID, git commit).

**Returns:**
- If `attempts == 1`: Returns a single `EvaluationResult` dictionary.
- If `attempts > 1`: Returns a list of `EvaluationResult` dictionaries.

---

### `AgentAdapterRegistry`
Manages agent communication protocols. Plugins can register custom adapters via the `on_discover_adapters` hook.

**Registration:**
```python
from eval_runner.engine import AgentAdapterRegistry

async def my_custom_adapter(payload: dict, endpoint: str):
    # Your communication logic here...
    return {"action": "final_answer", "summary": "Success"}

AgentAdapterRegistry.register("my-protocol", my_custom_adapter)
```

**Standard Protocols:**
- `http`: Communicates with a JSON REST API.
- `local`: Communicates with a subprocess via Stdin/Stdout.
- `socket`: Communicates via persistent TCP/Unix sockets.
- `human`: Interactive HITL (Human-In-The-Loop) adapter.

---

## 📂 Scenario Loading API

### `loader.load_scenario`
Loads scenarios from local files or remote Benchmark URIs.

**Signature:**
```python
def load_scenario(path: Union[str, Path]) -> Union[dict, list]
```

**Key Features:**
- **Benchmark URIs**: Supports `gaia://[split]`, `assistantbench://[split]`, etc.
- **Path Decoupling**: If `dataset.path` in the scenario is relative (e.g., `./data.csv`), it is automatically resolved relative to the scenario file location.
- **Schema Validation**: All loaded JSON scenarios are validated against the official `scenario.schema.json`.

---

### `loader.load_dataset`
Batch loads scenarios from a file or directory.

**Signature:**
```python
def load_dataset(file_path: Union[str, Path], format_type: Optional[str] = None) -> List[dict]
```
- **Directories**: Passing a directory path triggers a recursive search for all `.json` files.
- **Formats**: Auto-detects `.json`, `.jsonl`, and `.csv`.

---

## ⚖️ Metrics API

### `MetricRegistry`
A central registry for all evaluation metrics. Metrics are stateless functions that take expected vs actual data and return a float (0.0 to 1.0).

**Example:**
```python
from eval_runner.metrics import MetricRegistry
metric_func = MetricRegistry.get("state_verification")
score = metric_func(expected_changes, actual_state)
```

### Core Metric Catalog

| Metric Key | Function Signature | Description |
| :--- | :--- | :--- |
| `tool_call_correctness` | `(expected: list, actual: list)` | Exact set-match of tool names. |
| `state_verification` | `(expected: list, actual: dict)` | Parity check using **dot-notation** (e.g., `user.id`). |
| `luna_judge_score` | `(criterion: dict, context: dict)` | Async semantic similarity using an LLM. |
| `policy_compliance` | `(history: list)` | Detects `"status": "policy_violation"` in trajectory. |
| `pii_safety` | `(criterion: dict, summary: str)` | Detects leaked emails or phone numbers. |
| `delegation_loop_risk` | `(agent_sequence: list)` | Detects infinite cycles in multi-agent handoffs. |
| `refusal_calibration` | `(criterion: dict, summary: str)` | Measures if the agent refused correctly. |

---

## 🔌 Plugin & Event System

The core broadcasts events via `plugins.manager.trigger`. You can register a `BaseEvalPlugin` subclass to intercept:
- `on_discover_adapters`: Register new agent protocols.
- `on_register_commands`: Add custom CLI subcommands.
- `on_agent_turn_start`: Stream real-time state to the **Visual Debugger**.
- `on_tool_result`: Capture data for grounding heatmaps.
