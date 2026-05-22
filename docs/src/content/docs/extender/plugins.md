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
        print(f"Starting evaluation for {context.identifier}!")

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

:::important
The harness no longer supports the combined `"module": "path.Class"` string format for persistent registration. You **must** provide the `module` and `class` fields as separate entities in the registry.
:::

---

## 🏗️ Lifecycle Hooks

The plugin system provides hooks at every stage of the evaluation loop.

| Hook | Arguments | Description |
| :--- | :--- | :--- |
| **`before_evaluation`** | `context: EvaluationContext` | Setup task-level state or mocks. |
| **`on_agent_turn_start`** | `context: TurnContext` | Intercept the conversation flow. |
| **`on_turn_end`** | `context: TurnContext` | Observe results after an agent turn. |
| **`on_tool_request`** | `context`, `tool`, `args` | **Interception Point**. Return `False` to block. |
| **`on_tool_result`** | `context`, `tool`, `result` | Observe tool outputs for drift detection. |
| **`on_diagnose_failure`**| `taxonomy` | **v1.6.0**. Register custom forensic analyzers. |
| **`on_error`** | `context`, `exception` | Handle unhandled core exceptions. |

---

## 🧬 Typed Context Objects

To prevent prototype pollution and maintain forensic integrity, all hooks receive **Frozen Dataclasses**. You cannot modify them directly; use `plugin_data` for state sharing.

### 1. `EvaluationContext`
Represents the global state of a single scenario execution.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `str` | Forensic ID of the scenario. |
| `scenario_data`| `dict` | **Immutable**. The full AES JSON definition. |
| `metadata` | `dict` | **Immutable**. Global tags (difficulty, industry). |
| `plugin_data` | `dict` | **Mutable**. Safe bucket for plugin state. |
| `grounding_hits`| `dict` | Real-time map of tool and policy usage. |

### 2. `TurnContext`
Encapsulates the state of a single conversation turn.

| Field | Type | Description |
| :--- | :--- | :--- |
| `task_id` | `str` | Identifier for the current subtask. |
| `turn_number` | `int` | 1-based index of the current turn. |
| `history` | `tuple` | **Immutable**. Full message history. |
| `agent_response` | `dict` | Parsed agent action (available in `on_turn_end`). |
| `span_context` | `dict` | **Immutable**. Distributed tracing metadata. |

---

## 🔐 Trusted Extensions (v1.6.0)

To ensure both performance and security, AgentV implements a **3-Tier Trust Hierarchy**. Plugins and Shims can be marked as `trusted` in their registration metadata.

### 1. The Trust Tiers
*   **CORE**: Internal engine logic (Always Trusted). Full access to session metadata and hardware telemetry.
*   **TRUSTED**: Sanctioned Enterprise extensions. **Zero-copy access** to history and state.
*   **UNTRUSTED**: Third-party or community extensions. **Isolated via Deep-Copy** to prevent accidental or malicious state mutation.

### 2. Performance Optimization
By marking an industrial plugin as trusted, you eliminate the CPU/Memory overhead of `deepcopy` on large conversation traces. This is highly recommended for high-throughput evaluation pipelines.

```json
{
  "id": "enterprise-logger",
  "module": "ent.log",
  "class": "Logger",
  "trusted": true
}
```

:::caution
**Security Gate**: Only mark extensions as trusted if you have full control over the source code. Trusted extensions have the capability to modify the `EvaluationContext` and environment state in-place.
:::

---

## 🔒 Security & Iframe Protocols

Plugins extending the **Integrated Console** render in a secure, sandboxed environment.

### 1. Security Boundaries
- **Iframe Sandboxing**: `allow-scripts allow-forms allow-popups` are enabled. Top-level navigation is **blocked**.
- **Origin Validation**: All `postMessage` events are validated against the expected origin.

### 2. Secure PostMessage Communication
Custom components must use `window.parent.postMessage` to communicate with the core UI:
```javascript
window.parent.postMessage({
    type: 'NOTIFY',
    payload: { message: 'Analysis complete!', type: 'success' }
}, window.location.origin);
```

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

## ⛓️ Registering Custom Interceptors (v1.6.3)

Plugins can dynamically hook into the **Cryptographic Trace Signing**, **Tool Sandbox Isolation**, and **Adversarial Scenario Mutation** pipelines at runtime. This allows extensions to intercept signing, audit sandbox operations, or inject custom adversarial perturbations.

### 1. Registering a Tool Sandbox Interceptor
Custom plugins can register a `ToolSandboxInterceptor` using `tool_sandbox_service.register_interceptor(...)` inside the `before_evaluation` hook.

```python
from eval_runner.plugins import BaseEvalPlugin
from eval_runner.tool_sandbox import ToolSandboxInterceptor, tool_sandbox_service

class SecurityAuditingInterceptor(ToolSandboxInterceptor):
    def isolate(self, execute_fn, command, params):
        # Intercept before execution
        if command == "terminal" and "rm" in params.get("args", []):
            return {"status": "blocked", "message": "Destructive terminal commands are forbidden"}
        
        # Call original tool execution
        result = execute_fn(command, params)
        
        # Audit tool result
        result["audited"] = True
        return result

class SecurityGatePlugin(BaseEvalPlugin):
    def before_evaluation(self, context):
        # Register sandbox execution interceptor
        tool_sandbox_service.register_interceptor(SecurityAuditingInterceptor())
```

### 2. Registering a Trace Verification Interceptor
Custom plugins can register a `TraceVerificationInterceptor` to securely sign metadata or implement a custom cryptographic verifier.

```python
from eval_runner.plugins import BaseEvalPlugin
from eval_runner.verifier import TraceVerificationInterceptor, verification_service

class CustomKmsSigner(TraceVerificationInterceptor):
    def can_sign(self, manifest, format) -> bool:
        return format == "enterprise-hsm"

    def sign(self, manifest, format) -> dict:
        # Call KMS API to sign manifest hash
        signature = call_external_hsm(manifest)
        manifest["provenance_chain"].append({
            "identity": "hsm_signer",
            "signature": signature
        })
        return manifest

class EnterpriseHsmPlugin(BaseEvalPlugin):
    def before_evaluation(self, context):
        verification_service.register_interceptor(CustomKmsSigner())
```

### 3. Registering an Adversarial Scenario Mutator
Custom plugins can register a `ScenarioMutator` using `mutation_service.register_provider(...)` to dynamically intercept and customize how adversarial variants are generated.

```python
from eval_runner.plugins import BaseEvalPlugin
from eval_runner.mutator import ScenarioMutator, mutation_service

class IndustrialScenarioAugmentor(ScenarioMutator):
    def can_mutate(self, mutation_type: str) -> bool:
        return mutation_type == "industrial_perturbation"

    def mutate(self, scenario: dict, mutation_type: str, next_mutator) -> dict:
        # Apply custom perturbation
        modified_scenario = add_industrial_noise(scenario)
        # Delegate to next mutator in chain
        return next_mutator(modified_scenario, mutation_type)

class ScenarioAugmentPlugin(BaseEvalPlugin):
    def before_evaluation(self, context):
        mutation_service.register_provider(IndustrialScenarioAugmentor())
```

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
