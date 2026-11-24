---
title: Plugin Development Guide
description: Build industrial-grade extensions for the zero-touch AgentV OS Runtime.
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
pip install -r requirements-dev.txt

# 3. Run linting and the core test suite
ruff check .
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
[project.entry-points."agentv_runtime.plugins"]
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

:::note[Important]
The harness no longer supports the combined `"module": "path.Class"` string format for persistent registration. You **must** provide the `module` and `class` fields as separate entities in the registry.
:::

---

## 🏗️ Lifecycle & Interceptor Hooks

`BaseEvalPlugin` provides both typed abstract interface hooks and automatic dynamic event bus bridging.

### Native Interface Hooks
| Hook | Arguments | Description |
| :--- | :--- | :--- |
| **`before_evaluation`** | `context, span_context=None` | Pre-scenario setup, connection initialization, and span tagging. |
| **`after_evaluation`** | `context, results, span_context=None` | Post-run teardown, artifact publishing, and metric export. |
| **`on_step_start`** | `context=None, node_id=None, node_data=None` | Workflow DAG node activation hook. |
| **`on_step_end`** | `context=None, node_id=None, verdict=None` | Workflow DAG node completion and verdict hook. |
| **`on_tool_request`** | `context, tool_name, arguments=None` | **Interception Point**. Return `True` to allow, `False` to reject, or `{"arguments": {...}}` to replace parameters. |
| **`on_before_commit`** | `context, state_diff=None` | State transition gate. Return `True` to commit, `False` to abort. |
| **`on_rollback`** | `context, compensation_action=None` | Compensating rollback execution hook. |
| **`on_approval_preflight`** | `context, node_data=None` | Reject an approval-capable node before external agent invocation. |
| **`on_approval_request`** | `context, approval_data=None` | Human-in-the-loop permission evaluation. Return `True`/`False`. |
| **`on_approval_created`** | `context, request` | Durable approval request notification dispatch. |
| **`on_approval_resolved`** | `context, request` | Approval decision resolution audit hook. |
| **`on_artifact_created`** | `run_id, artifact_name, artifact_path, metadata=None` | Evidence artifact commit listener (SOC 2 CC6.8). |
| **`on_register_commands`** | `registry` | Declared compatibility hook; not called by CLI initialization. Use `agentv_runtime.cli_extensions` entry points. |
| **`on_discover_adapters`** | `registry` | Register custom agent communication adapters. |
| **`on_register_simulators`**| `registry` | Register custom World Shims. |
| **`on_discover_metrics`** | `registry` | Register custom evaluation metrics. |
| **`on_diagnose_failure`**| `taxonomy` | Register custom forensic failure analyzers. |
| **`on_register_console_routes`** | `app, nav_registry` | Register custom Flask API routes and React sidebar tabs. |

Dynamic interceptor hooks also include `on_approval_resolution(context, approval_data)`
(decision filtering), `on_tool_result(context, tool_name, result)` (result filtering
before delivery), and `on_tool_delivered(context, tool_name, result)` (notification
after the delivery/history boundary). These are invoked by name and are not
declared BaseEvalPlugin methods. A result interceptor can reject with `False` or
replace a result with `{"result": ...}`. Event-bridge callbacks can share names;
accept the relevant positional arguments and event keyword payloads when
implementing both paths. See [hooks](/extender/hooks/).

### Dynamic Event Bus Bridge
Additionally, any event emitted over the session `EventEmitter` automatically dispatches to an `on_<event_name.lower()>(self, context, **event_data)` hook on loaded plugins (e.g., `on_turn_start`, `on_turn_end`, `on_tool_call`, `on_tool_result`, `on_external_tool_call`, `on_external_tool_result`, `on_hitl_pause`, `on_hitl_resume`).

---

## 🧬 Typed Context Objects

Evaluation and turn hooks use frozen dataclasses, while discovery and some dynamic hooks receive other objects. Frozen fields prevent attribute reassignment, not recursive mutation of every nested value. Use `plugin_data` for intentional plugin state.

### 1. `EvaluationContext`
Represents the global state of a single scenario execution.

| Field | Type | Description |
| :--- | :--- | :--- |
| `identifier` | `str` | Forensic ID of the scenario. |
| `scenario_data`| `dict` | Deep-copied and wrapped in a top-level read-only mapping; nested values are not recursively frozen. |
| `metadata` | `dict` | Deep-copied and wrapped in a top-level read-only mapping. |
| `plugin_data` | `dict` | **Mutable**. Safe bucket for plugin state. |
| `grounding_hits`| `dict` | Real-time map of tool and policy usage. |

### 2. `TurnContext`
Encapsulates the state of a single conversation turn.

| Field | Type | Description |
| :--- | :--- | :--- |
| `task_id` | `str` | Identifier for the current subtask. |
| `turn_number` | `int` | 1-based index of the current turn. |
| `history` | `tuple` | A tuple; list input is deep-copied on construction. Dictionaries inside the tuple remain mutable. |
| `agent_response` | `dict` | Parsed agent action (available in `on_turn_end`). |
| `span_context` | `dict` | Optional tracing dictionary; frozen dataclass fields do not recursively freeze this dictionary. |

---

## Metric provenance and copying

Metric source `CORE` bypasses hydration copies. For every non-CORE metric source,
including trusted sources, requested mutable history/state dictionaries and lists
are deep-copied. Trust separately controls access to `session_metadata` and
`forensic_telemetry`; it does not grant zero-copy history access.

PluginManager records provenance and trust from the loading origin. A JSON
`trusted: true` field alone does not establish trusted provenance. These controls
are in-process API conventions, not an isolation boundary for arbitrary Python
code. See [trust and copying](/spec/forensics/trust-hierarchy/).

## Console extension trust

Remote React extensions mount in the host application; they are not iframe
sandboxes. Production permits backend-verified official publishers and rejects
unsigned/community execution. Entry/chunk SRI, signed sidecars, API compatibility
and permission declarations are checked before loading. Mounted pages receive
ExtensionRuntimeContextApi rather than a postMessage iframe protocol.

Follow the [GUI extension workflow](/extender/gui-extensions/) to publish and
activate a complete signed release. A navigation `remoteEntry` or self-declared
`tier` does not establish publisher trust or supply the required sidecar.

Plugin hooks use `PLUGIN_TIMEOUT` (default five seconds). A timeout must not be
used to bypass mandatory security/evidence rejection semantics.

## 🌐 Extending Environment Simulators

The `on_register_simulators` hook allows you to inject **World Shims** (Zero-Touch Environment Mocks).

```python
class MyCloudPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry):
        # Register the S3 Simulator
        registry["s3_bucket"] = S3Simulator
```

Once registered, any scenario referencing `s3_bucket` will automatically use this logic.

---

## ⛓️ Registering Custom Interceptors (v1.6.3)

Plugins can dynamically hook into the **Cryptographic Trace Signing**, **Tool Sandbox Isolation**, and **Adversarial Scenario Mutation** pipelines at runtime. This allows extensions to intercept signing, audit sandbox operations, or inject custom adversarial perturbations.

### 1. Registering a Tool Sandbox Interceptor
Custom plugins can register a `ToolSandboxInterceptor` using `tool_sandbox_service.register_interceptor(...)` inside the `before_evaluation` hook.

```python
from collections.abc import Callable, Coroutine
from eval_runner.plugins import BaseEvalPlugin
from eval_runner.tool_sandbox import ToolSandboxInterceptor, tool_sandbox_service


class SecurityAuditingInterceptor(ToolSandboxInterceptor):
    def can_isolate(self, tool_name: str) -> bool:
        # Determine if this interceptor targets the tool
        return tool_name == "terminal"

    async def isolate_call(
        self,
        call_data: dict,
        next_executor: Callable[[dict], Coroutine[None, None, dict]],
    ) -> dict:
        # Intercept before execution
        arguments = call_data.get("params", {})
        if "rm" in arguments.get("args", []):
            return {"status": "blocked", "message": "Destructive terminal commands are forbidden"}

        # Call next executor in the pipeline
        result = await next_executor(call_data)

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
from collections.abc import Callable
from eval_runner.plugins import BaseEvalPlugin
from eval_runner.verifier import TraceVerificationInterceptor, verification_service


class CustomKmsSigner(TraceVerificationInterceptor):
    def can_sign(self, format: str) -> bool:
        return format == "enterprise-hsm"

    def sign(self, manifest: dict, next_signer: Callable[[dict], dict]) -> dict:
        # Preempt/Modify manifest before signing
        manifest["custom_kms_certified"] = True

        # Call KMS API to sign manifest hash
        signature = call_external_hsm(manifest)
        manifest["provenance_chain"].append({"identity": "hsm_signer", "signature": signature})

        # Delegate down the pipeline
        return next_signer(manifest)


class EnterpriseHsmPlugin(BaseEvalPlugin):
    def before_evaluation(self, context):
        verification_service.register_interceptor(CustomKmsSigner())
```

### 3. Registering an Adversarial Scenario Mutator
Custom plugins can register a `ScenarioMutator` using `mutation_service.register_provider(...)` to dynamically intercept and customize how adversarial variants are generated.

```python
from eval_runner.plugins import BaseEvalPlugin
from eval_runner.mutations.mutator import ScenarioMutator, mutation_service


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

## Console GUI extensions

Python plugins can add protected backend routes through
`on_register_console_routes`. Publish frontend contributions through the signed
[extension workflow](/extender/gui-extensions/), including route permissions,
publisher identity, SRI and a production React peer declaration. Server routes
must independently enforce authentication, permissions and active scope.

## 🔌 Framework Adapters

Extend agent communication protocols using the `on_discover_adapters` hook. 

### Supported Adapters (2026 Baseline)
- **`langgraph://`**: LangGraph adapter (repository pin: 1.2.24).
- **`crewai://`**: Agent Swarm integration.
- **`gemini://`**: Official **google-genai 3.6.1** SDK.
- **`ollama://`**, **`openai://`**, **`grok://`**: Direct LLM provider shims.

---

## ⚖️ Judge Layer Extensions (Luna-Judge)

Developers can extend the **Luna-Judge** layer:
1. **Custom Rubrics**: Dynamically register domain-specific evaluation rules.
2. **Judge Providers**: Add custom models via the `LLMProviderFactory` to serve as the evaluation judge.
