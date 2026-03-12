# Plugin Development Guide

The AI Agent Evaluation Harness is built on a strict "Zero-Touch Core" philosophy. This means that you should rarely, if ever, modify the `eval_runner` core engine directly. Instead, almost all custom business logic, API integrations, and new CLI commands should be injected via plugins.

## Developer Quick Setup
Before building a plugin, set up your local development environment:

```bash
# 1. Clone & activate virtual environment
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate # Mac/Linux

# 2. Install dependencies & dev tools
pip install -e .
pip install pytest flake8 black mypy

# 3. Run the core test suite to ensure stability
pytest tests/ -v -p no:plugin_gateway
```

## Creating a Plugin

Plugins are Python classes that inherit from `eval_runner.plugins.BaseEvalPlugin`.

```python
from eval_runner.plugins import BaseEvalPlugin

class MyCustomPlugin(BaseEvalPlugin):
    def before_evaluation(self, context):
        print(f"Starting evaluation for {context.scenario_id}!")

    def on_tool_request(self, context, tool_name, args):
        if tool_name == "sensitive_tool":
            return False  # Block the tool call
        return True
```

## Lifecycle Hooks

| Hook | Arguments | Description |
|---|---|---|
| `before_evaluation` | `context: EvaluationContext` | Triggered before the evaluation starts. |
| `on_agent_turn_start` | `context: TurnContext` | Triggered before each agent turn. |
| `on_turn_end` | `context: TurnContext` | Triggered after each turn. |
| `on_tool_request` | `context`, `tool_name`, `args` | **Interception Point**. Return `False` to block. |
| `on_tool_result` | `context`, `tool_name`, `result` | Observe the output of a tool call. |
| `on_error` | `context`, `exception` | Called on unhandled exceptions. |
| `on_discover_adapters` | `registry` | Register custom agent protocols (e.g., `grpc://`). |
| `on_metrics_calculated` | `context`, `results` | Post-metric hook for cross-attempt aggregation. |
| `after_evaluation` | `context`, `results` | Final hook after evaluation completes. |
| `on_register_commands` | `registry: CommandRegistry` | Register CLI subcommands under the plugin namespace. |
| `on_register_console_routes` | `app: Flask`, `nav: list` | Inject custom REST routes and React navigation links to the [Integrated Visual Suite](#extending-the-visual-suite). |

> **⚠️ Security Note:** The legacy `extend_cli` hook has been **removed** to prevent command hijacking. All plugins must use `on_register_commands` which isolates commands under `eval-harness plugin <plugin_name>`.

## Typed Context Objects

To ensure security and prevent Prototype Pollution, all hooks receive **Frozen Dataclasses**. Plugins cannot modify existing context fields; they must use the `plugin_data` bucket for state sharing.

### 1. `EvaluationContext`
Passed to `before_evaluation`, `after_evaluation`, and `on_metrics_calculated`.

| Field | Type | Description |
| :--- | :--- | :--- |
| `scenario_id` | `str` | Unique ID of the current scenario. |
| `scenario_data`| `dict` | **Read-Only** copy of the full AES JSON scenario. |
| `metadata` | `dict` | Global metadata (difficulty, industry, etc.). |
| `plugin_data` | `dict` | **Mutable** bucket for cross-turn plugin state. |
| `grounding_hits`| `dict` | Real-time map of tool and policy usage. |

### 2. `TurnContext`
Passed to turn-level hooks (`on_agent_turn_start`, `on_tool_request`, etc.).

| Field | Type | Description |
| :--- | :--- | :--- |
| `task_id` | `str` | Current turn/subtask identifier. |
| `turn_number` | `int` | Current turn index (1-based). |
| `current_message`| `str` | The latest raw input from the user/environment. |
| `history` | `tuple` | **Immutable** history of the conversation so far. |
| `agent_response` | `dict` | Parsed agent action (available in `on_turn_end`). |

## Plugin Timeout Enforcement

All plugin hooks are subject to a **5-second timeout** (`PLUGIN_TIMEOUT = 5.0`). If a plugin hook hangs (e.g., due to a network request), the engine will terminate it and continue execution. This prevents a single misbehaving plugin from freezing the entire evaluation loop.

## Registering Commands (Secure Namespace)

Plugins register CLI subcommands via the `on_register_commands` hook. Commands are automatically scoped under `eval-harness plugin <plugin_name>`:

```python
class MyReportPlugin(BaseEvalPlugin):
    def on_register_commands(self, registry):
        sub = registry.register_command("generate", self.handle_generate, help_text="Generate a report")
        sub.add_argument("--format", default="html")

    def handle_generate(self, args):
        print(f"Generating {args.format} report...")
```

Usage: `eval-harness plugin myreport generate --format html`

## Extending the Visual Suite (Integrated Console)

Plugins can inject custom views into the `eval-harness console` (the unified React SPA). This replaces the legacy Admin Console.

### 1. Secure Route Registration
The `on_register_console_routes` hook provides access to the underlying Flask `app` and a `nav_registry` for the sidebar.

```python
def on_register_console_routes(self, app, nav_registry):
    nav_registry.append({
        "id": "my_plugin_tab",
        "title": "My Analysis",
        "path": "/plugin/my-tab",
        "icon": "chart-bar"
    })
```

For detailed React component mapping, see the [UI Migration Guide](file:///C:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/docs/guides/help/UI_MIGRATION_GUIDE.md).

## Advanced Patterns: Zero-Touch Observers

The preferred way to bridge internal engine state to external systems (like the Visual Debugger or a custom SIEM) is the **Zero-Touch Observer** pattern. 

### Case Study: `RemoteBridgePlugin`
Instead of modifying the core evaluation loop, the bridge uses standard lifecycle hooks to push state updates via HTTP.

```python
class RemoteBridgePlugin(BaseEvalPlugin):
    def on_agent_turn_start(self, context):
        # Push current turn state to the listener
        requests.post(self.endpoint, json={
            "event": "turn_start",
            "scenario": context.scenario_id,
            "turn": context.turn_number
        })
```
This pattern ensures that the core engine remains totally unaware of the debugger and can operate even if the bridge is removed or fails.

## Extending Core Capabilities

Plugins aren't just for logging; they can extending the core evaluation engine capabilities.

### Example: Creating a Custom Metric
Instead of modifying `eval_runner.metrics`, write a plugin that hooks into `on_metrics_calculated` to inject new scores.

```python
from eval_runner.plugins import BaseEvalPlugin

class SentimentMetricPlugin(BaseEvalPlugin):
    def on_metrics_calculated(self, context, results):
        # Calculate sentiment on the final answer
        answer = context.final_state.get("answer", "")
        sentiment_score = 1.0 if "great" in answer.lower() else 0.0
        
        # Inject the metric into the results payload
        results["metrics"]["custom_sentiment"] = sentiment_score
        results["passed"] = results["passed"] and (sentiment_score == 1.0)
```

## Advanced Platform Utilities

Phase 6 and 7 introduced high-level automation tools that leverage the plugin system and event bus:
- **`explain <run.jsonl>`**: Uses heuristic pattern matching (expandable via plugins) to diagnose agent failures.
- **`analyze <url>`**: Scans agent codebases; plugins can register new "Tool Signature" detectors to improve scanning accuracy.
- **Visual AES Builder**: A drag-and-drop integrated logic builder for complex AES flows, accessible via the Admin Console.

## Registering Plugins

Plugins are automatically discovered if they are registered as entry points under the `eval_runner.plugins` group:

```toml
# pyproject.toml
[project.entry-points."eval_runner.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

## Framework Adapters (Advanced)

Phase 4 introduced built-in support for extending agent communication protocols without touching the core engine. Using the `on_discover_adapters` hook, a plugin can register custom protocol schemes (e.g., `langgraph://`).

```python
from eval_runner.plugins import BaseEvalPlugin

class LangGraphAdapterPlugin(BaseEvalPlugin):
    def on_discover_adapters(self, registry):
        registry.register("langgraph", self.execute_langgraph_node)

    async def execute_langgraph_node(self, payload: dict) -> dict:
        """Custom execution logic specific to LangGraph."""
        return {"action": "final_answer", "summary": "LangGraph Execution Complete."}
```
If this plugin is active, scenarios can now specify an agent URL like `langgraph://my_agent_node`, and the engine will seamlessly route the task to this adapter bypassing standard HTTP mechanisms.

### Ecosystem Provider Adapters
Providers like **OpenAI**, **Gemini**, and **Claude** are also implemented using this hook. While framework adapters (like LangGraph) often wrap complex logic, provider adapters typically translate AES tasks into specific LLM API calls.

