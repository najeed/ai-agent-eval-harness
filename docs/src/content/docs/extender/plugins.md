---
title: Plugin Development Guide
description: Build industrial-grade extensions for the zero-touch AgentV core.
---

AgentV is built on a strict **Zero-Touch Core** philosophy. All custom business logic, API integrations, and industry-specific CLI commands are injected via the modular Plugin System.

## 🛠️ Developer Quick Setup

Before building a plugin, set up your local development environment:

```bash
# 1. Clone & activate virtual environment
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness
python -m venv venv
venv\Scripts\activate  # Windows

# 2. Install dependencies & dev tools
pip install -e .
pip install pytest flake8 black mypy

# 3. Run the core test suite
pytest tests/ -v
```

## 🧩 Creating a Plugin

Plugins are Python classes that inherit from `eval_runner.plugins.BaseEvalPlugin`.

```python
from eval_runner.plugins import BaseEvalPlugin

class MyCustomPlugin(BaseEvalPlugin):
    def before_evaluation(self, context):
        print(f"Starting evaluation for {context.scenario_id}!")

    def on_tool_request(self, context, tool_name, args):
        if tool_name == "sensitive_tool":
            return False  # Block the tool call security check
        return True
```

### Registration & Discovery

Plugins can be registered and discovered in two primary ways:

#### 1. Python Entry-Points (Dynamic)
Define your plugins in `pyproject.toml` for automatic discovery when your package is installed:

```toml
[project.entry-points."eval_runner.plugins"]
my_analysis = "my_package.plugin:MyAnalysisPlugin"
```

#### 2. Persistent Registry (Enterprise/External)
For plugins that are not installed as packages, use the `agentv plugin register` CLI command. This saves the registration to the local `.aes/config/plugins/registry.json` file.

```bash
agentv plugin register /path/to/my_plugin_dir/
```

### 🔍 Listing Plugins
You can list all active and persistently registered plugins using either the namespaced command or the shorthand alias:

```bash
agentv plugin list
# OR
agentv list-plugins
```

### 🧬 Forensic Registry Schema
When registering plugins persistently, AgentV enforces a strict **Split Schema** to ensure industrial-grade clarity and prevent package resolution ambiguity.

**Registry Location**: `.aes/config/plugins/registry.json`

**Correct Schema Example**:
```json
{
  "plugins": [
    {
      "id": "enterprise-adapter",
      "name": "enterprise-adapter",
      "module": "enterprise.adapter.plugin",
      "class": "AdapterPlugin",
      "enabled": true,
      "config": {}
    }
  ]
}
```

> [!IMPORTANT]
> The harness no longer supports the combined `"module": "path.Class"` string format for persistent registration. You **must** provide the `module` and `class` fields as separate entities in the registry.

---

## 🏗️ Lifecycle Hooks

The plugin system provides hooks at every stage of the evaluation loop.

| Hook | Arguments | Description |
| :--- | :--- | :--- |
| **`before_evaluation`** | `context: EvaluationContext` | Setup task-level state or mocks. |
| **`on_agent_turn_start`** | `context: TurnContext` | Intercept the conversation flow. |
| **`on_tool_request`** | `context`, `tool`, `args` | **Critical Security Hook**. Block or modify tools. |
| **`on_tool_result`** | `context`, `tool`, `result` | Observe tool outputs for drift detection. |
| **`on_register_commands`**| `registry` | Inject custom commands into the `agentv` CLI. |
| **`on_register_console_routes`** | `app`, `nav` | Add custom views to the [Integrated Console](/extender/api-reference/). |

---

## 🔒 Security & Data Integrity

To prevent prototype pollution and maintain forensic integrity, all hooks receive **Frozen Context Objects**.

1. **`EvaluationContext`**: Global state for a single run. Includes `scenario_data` (Immutable) and `plugin_data` (Mutable).
2. **`TurnContext`**: State for a single turn. Includes `history` (Immutable) and `agent_response`.

### Plugin Timeout
All plugin hooks are subject to a **5-second timeout** (`PLUGIN_TIMEOUT`). If a hook hangs, the engine logs a `PluginTimeoutError` and proceeds, ensuring the industrial pipeline doesn't stall.

---

## 🌐 Extending Environment Simulators

The `on_register_simulators` hook allows you to inject **World Shims** (Zero-Touch Environment Mocks).

```python
class MyCloudPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry):
        # Register the S3 Simulator
        registry["s3_bucket"] = S3Simulator()
```

Once registered, any scenario referencing `s3_bucket` will automatically use this logic.

---

## ⚡ Integrated Console Extension

Plugins can inject custom React views and REST endpoints into the [Harness Console](/extender/api-reference/).

```python
class AdminAnalysisPlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        # Register a backend API endpoint
        @app.route("/api/plugin/analysis/summary")
        def get_summary():
            return {"status": "ok", "insights": ["High latency"]}

        # Add a link to the Sidebar
        nav_registry.append({
            "id": "analysis_tab",
            "title": "Live Analysis",
            "path": "/api/plugins/analysis",
            "icon": "vitals",
            "type": "component"
        })
```

---

## 🔌 Framework Adapters

Extend agent communication protocols using the `on_discover_adapters` hook. 

### Supported Adapters (2026 Baseline)
- **`langgraph://`**: LangGraph v2 Support.
- **`crewai://`**: Agent Swarm integration.
- **`gemini://`**: Official **google-genai v1.70.0** SDK.
- **`ollama://`**, **`openai://`**, **`grok://`**: Direct LLM provider shims.

---

## ⚖️ Judge Layer Extensions (Luna-Judge)

Developers can extend the **Luna-Judge** layer:
1. **Custom Rubrics**: Dynamically register domain-specific evaluation rules.
2. **Judge Providers**: Add custom models via the `LLMProviderFactory` to serve as the evaluation judge.
