# Plugin Development Guide

The AI Agent Evaluation Harness is built on a "Zero-Touch" core, meaning almost any functionality can be extended or modified via plugins without touching the core engine.

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

> **⚠️ Security Note:** The legacy `extend_cli` hook has been **removed** to prevent command hijacking. All plugins must use `on_register_commands` which isolates commands under `eval-harness plugin <plugin_name>`.

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
        registry["langgraph"] = self.execute_langgraph_node

    async def execute_langgraph_node(self, payload: dict) -> dict:
        """Custom execution logic specific to LangGraph."""
        return {"action": "final_answer", "summary": "LangGraph Execution Complete."}
```
If this plugin is active, scenarios can now specify an agent URL like `langgraph://my_agent_node`, and the engine will seamlessly route the task to this adapter bypassing standard HTTP mechanisms.

