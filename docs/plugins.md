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
| `on_register_console_routes` | `app: Flask`, `nav: list` | Inject custom REST routes and React Native UI navigation links to the Admin Console. |

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

## Extending the Admin Console GUI (Unified React SPA)

Plugins can inject custom views and navigation links into the `eval-harness console` using the **Secure Handoff Architecture**. This ensures Enterprise-grade security while maintaining a "Zero-Touch" core.

### 1. Registering the Navigation Link
The `on_register_console_routes` hook allows you to append items to the `nav_registry`. The console will automatically render these in the sidebar.

### 2. Implementation Modes
- **Mode A (JSON)**: Return a structured JSON spec that the console renders using premium React components.
- **Mode B (External)**: Register external links or documentation paths.

```python
from flask import Blueprint, jsonify
from eval_runner.console.auth import handoff_required

class AuditPlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        # 1. metadata must include type="plugin"
        nav_registry.append({
            "id": "audit_log", 
            "title": "Security Audit", 
            "path": "/api/plugin/audit", 
            "icon": "shield",
            "type": "plugin"
        })
        
        bp = Blueprint("audit", __name__)
        
        @bp.route("/api/plugin/audit")
        @handoff_required # Mandatory for Enterprise security
        def get_audit():
            # Returning JSON triggers Mode A
            return jsonify({
                "title": "Audit Dashboard",
                "items": [{"label": "Status", "value": "Secure"}]
            })
            
        app.register_blueprint(bp)
```

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

## Visionary Platform Utilities

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

