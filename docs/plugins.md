# Plugin Development Guide

The MultiAgentEval is built on a strict "Zero-Touch Core" philosophy. This means that you should rarely, if ever, modify the `eval_runner` core engine directly. Instead, almost all custom business logic, API integrations, and new CLI commands should be injected via plugins.

## Developer Quick Setup
Before building a plugin, set up your local development environment:

```bash
# 1. Clone & activate virtual environment
git clone https://github.com/najeed/ai-agent-multiagent-eval.git
cd ai-agent-multiagent-eval
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

Plugins are Python classes that inherit from `eval_runner.plugins.BaseEvalPlugin`. The base class is an `abc.ABC`, allowing for formal hook definitions.

```python
from eval_runner.plugins import BaseEvalPlugin
from abc import abstractmethod

class MyCustomPlugin(BaseEvalPlugin):
    # Optional: override specific hooks as needed
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
| `on_register_simulators`| `registry: dict` | Shim Registration. Add your World Shims to the registry. |
| `on_register_console_routes` | `app: Flask`, `nav: list` | Inject custom REST routes and React navigation links. |

> **⚠️ Security Note:** All plugins must use `on_register_commands` which isolates commands under `multiagent-eval plugin <plugin_name>`.

## Typed Context Objects

To ensure security and prevent Prototype Pollution (Audit Point #8), all hooks receive **Frozen Dataclasses**. These objects use `types.MappingProxyType` and deep-copying to ensure that internal engine state cannot be modified by a plugin. Plugins must use the `plugin_data` bucket for state sharing across tasks.

### 1. `EvaluationContext`
Passed to `before_evaluation`, `after_evaluation`, and `on_metrics_calculated`. It represents the global state of a single scenario execution.

| Field | Type | Description |
| :--- | :--- | :--- |
| `scenario_id` | `str` | Unique ID of the current scenario. |
| `scenario_data`| `dict` | **Immutable**. The full AES JSON scenario definition. |
| `metadata` | `dict` | **Immutable**. Global metadata (difficulty, industry, etc.). Contains `args` (a dictionary of CLI flags). |
| `global_state` | `dict` | **Immutable**. Shared engine-level configuration. |
| `plugin_data` | `dict` | **Mutable**. A safe bucket for plugins to store state that persists across all turns of this scenario. |
| `grounding_hits`| `dict` | Real-time map of tool and policy usage tracked by the engine. |

### 2. `TurnContext`
Passed to turn-level hooks (`on_agent_turn_start`, `on_tool_request`, etc.). It encapsulates the state of a single conversation turn.

| Field | Type | Description |
| :--- | :--- | :--- |
| `task_id` | `str` | Identifier for the current subtask/turn. |
| `turn_number` | `int` | 1-based index of the current turn. |
| `current_message`| `str` | The latest raw input (from user or environment). |
| `history` | `tuple` | **Immutable**. Tuple of message dictionaries representing the full chat history. |
| `agent_response` | `dict` | Parsed agent action (e.g., `{"tool": "...", "args": {}}`). Available in `on_turn_end`. |
| `metadata` | `dict` | Turn-specific metadata (timings, token counts). |

---

## Plugin Timeout Enforcement

All plugin hooks are subject to a **5-second timeout** (`PLUGIN_TIMEOUT = 5.0`). If a plugin hook hangs (e.g., waiting for an unresponsive external API), the engine will log a `PluginTimeoutError`, terminate the specific hook execution, and proceed. This ensures the evaluation loop remains resilient to misbehaving or slow extensions.

---

## Registering Commands (Secure Namespace)

Plugins register CLI subcommands via the `on_register_commands` hook. Commands are automatically scoped under `multiagent-eval plugin <plugin_name>` to prevent core command hijacking.

```python
class MyReportPlugin(BaseEvalPlugin):
    def on_register_commands(self, registry):
        # Registers: multiagent-eval plugin myreport generate
        sub = registry.register_command("generate", self.handle_generate, help_text="Generate a report")
        sub.add_argument("--format", default="html")

    def handle_generate(self, args):
        print(f"Generating {args.format} report...")
```

## Registering World Shims (Zero-Touch Environment)

The `on_register_simulators` hook allows plugins to provide custom environment mocks (World Shims) that the engine uses to simulate real-world tool consequences.

```python
class MyCloudPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry):
        # Add your simulator instance to the global registry
        registry["s3_bucket"] = S3Simulator()
```

Once registered, any scenario mentioning `s3_bucket` in its `tasks` will automatically use your simulator logic during evaluation.

---

## Extending the Visual Suite (Integrated Console)

Plugins can inject custom views and API endpoints into the `multiagent-eval console`.

### 1. Secure Route Registration
The `on_register_console_routes` hook provides access to the Flask `app` and a `nav_registry` list for the sidebar.

```python
from flask import jsonify

class AdminAnalysisPlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        # 1. Register a backend API endpoint
        @app.route("/api/plugin/analysis/summary")
        def get_summary():
            return jsonify({"status": "ok", "insights": ["High latency in turn 3"]})

        # 2. Add a link to the React Sidebar as a sandboxed component
        nav_registry.append({
            "id": "analysis_tab",
            "title": "Live Analysis",
            "path": "/api/plugins/analysis",
            "icon": "vitals",
            "type": "component"  # Renders in a secure sandboxed iframe
        })

### 2. Secure PostMessage Communication
Plugins rendered as `component` should use `window.parent.postMessage` to communicate with the core UI.
```javascript
window.parent.postMessage({
    type: 'NOTIFY',
    payload: { message: 'Analysis complete!', type: 'success' }
}, window.location.origin);
```

### 3. Security Boundaries
The core UI enforces strict security for plugin components:
- **Iframe Sandboxing**: `allow-scripts allow-forms allow-popups` are enabled. Top-level navigation is **blocked**.
- **Origin Validation**: All `postMessage` events are validated against the expected origin before processing.
```

For detailed React component mapping and HUD customization, see the [UI Migration Guide](guides/help/UI_MIGRATION_GUIDE.md).

---

## Advanced Patterns: Zero-Touch Observers

The preferred way to bridge internal engine state to external systems is the **Zero-Touch Observer** pattern. This ensures the core engine remains functional even if the external system is down.

### Case Study: `RemoteBridgePlugin`
The built-in `eval_runner/live_bridge_plugin.py` uses this pattern to push state updates to the Visual Debugger. It suppresses errors and uses short timeouts to maintain engine performance.

```python
import requests
from eval_runner.plugins import BaseEvalPlugin

class RemoteBridgePlugin(BaseEvalPlugin):
    def on_agent_turn_start(self, context):
        try:
            # Fast, non-blocking post to the debugger
            requests.post("http://localhost:5000/api/debugger/state", json={
                "event": "turn_start",
                "scenario": context.scenario_id,
                "turn": context.turn_number
            }, timeout=0.1)
        except Exception:
            pass # Zero-Touch: Engine core is unaffected by bridge failures
```

---

## Best Practices for Plugin Developers

1. **State Isolation**: Always use `context.plugin_data` for state. Do not attempt to use global variables or class-level state as multiple evaluations may run in parallel (e.g., via `Ray` in Enterprise).
2. **Error Resilience**: Wrap your hook logic in `try-except` blocks. An unhandled exception in a plugin will trigger the `on_error` hook, but may stop your plugin from processing further events in that run.
3. **Performance First**: Since hooks block the main evaluation loop, avoid heavy computation or slow network calls. Use asynchronous processing or background threads if necessary.
4. **Read-Only Mentality**: Treat all context data as read-only. Even if you manage to bypass the `frozen` protection, you risk causing non-deterministic behavior in metrics calculation.
5. **Namespacing**: When storing data in `plugin_data`, use your plugin's name as a key (e.g., `context.plugin_data["my_plugin"] = {...}`) to avoid collisions with other active plugins.

---

## Registering Plugins

Plugins are discovered via `entry-points` in `pyproject.toml`:

```toml
[project.entry-points."eval_runner.plugins"]
my_analysis = "my_package.plugin:MyAnalysisPlugin"
```

## Framework Adapters (Advanced)

There is built-in support for extending agent communication protocols without touching the core engine. Using the `on_discover_adapters` hook, a plugin can register custom protocol schemes (e.g., `langgraph://`).

Built-in Ecosystem Adapters:
- **`langgraph://`**: Integration with LangChain's LangGraph.
- **`crewai://`**: Support for CrewAI agent swarms.
- **`autogen://`**: Support for Microsoft AutoGen agents.
- **`grok://`**: Native xAI Grok API integration.
- **`ollama://`**, **`openai://`**, **`claude://`**, **`gemini://`**: Direct LLM provider shims.

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
Providers like **OpenAI**, **Gemini**, **Claude**, **Ollama**, and **xAI Grok** are also implemented using this hook. While framework adapters (like LangGraph or AutoGen) often wrap complex logic, provider adapters typically translate AES tasks into specific LLM API calls.

## ⚖️ Extending the Judge Layer (v3.1)

The harness features a pluggable LLM-as-judge layer (`Luna-Judge`). Developers can extend this in two ways:

### 1. Registering Custom Rubrics
Rubrics are stored in `eval_runner/rubrics.py` via the `RubricRegistry`. While you can add them directly to the registry for the core, you can also register them dynamically in a plugin:

```python
from eval_runner.rubrics import RubricRegistry

class MyCustomJudgePlugin(BaseEvalPlugin):
    def before_evaluation(self, context):
        # Register a domain-specific rubric
        RubricRegistry.register("my_industry", "Evaluate the agent based on [My Specialized Rules]...")
```

### 2. Custom Judge Providers
The judge uses the `LLMProviderFactory` to route scoring requests. By adding a custom adapter via `on_discover_adapters`, you can make new models available for judging by setting the `judge_provider` in your scenario's `judge_config`.

