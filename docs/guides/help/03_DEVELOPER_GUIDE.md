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

---

## 🧩 2) CLI Architecture

Entry point: `eval_runner/cli.py`

### Main commands
- `evaluate` — Run a batch of scenarios
- `quickstart` — End-to-end evaluation demo using `sample_agent`
- `console` — Launch the local React Native Web Dashboard for visual tracing
- `doctor` — Validate environment health and dependencies
- `init` — Scaffold new project directories with synthetic datasets
- `report` — Generate rich HTML reports from existing `.jsonl` traces
- `run` — Run a single scenario file
- `replay` — Replay a run trace
- `aes validate` — Validate AES benchmark definitions
- `spec-to-eval` — Convert Markdown specs into JSON scenarios
- `auto-translate` — Automatically translate documents into scenarios using Ollama
- `import-drift` — Convert production traces into scenarios
- `mutate` — Generate adversarial variants (typos, ambiguity, injection)
- `scenario generate` — Interactive generator for boilerplate scenarios
- `record` — Real-time agent interaction logger
- `playground` — Interactive CLI REPL for agent testing
- `install` — Rapid deployment of curated scenario packs
- `analyze` — Proactive agent codebase scanning and AES scaffolding
- `ci generate` — Instant GitHub Actions integration for evaluation
- `failures search` — Query the global Failure Corpus for edge cases
- `explain` — Automated trace diagnostics for root cause analysis

---

## 🧠 3) Evaluation Engine (Zero-Touch Core)

The core has been refactored into a decoupled, event-driven architecture to support Enterprise hot-swapping.

### 3.1 Architectural Components
1. **Runner (`runner.py`)**: Orchestrates the high-level evaluation loop, handling multi-attempt (`pass@k`) logic.
2. **SessionManager (`session.py`)**: Manages individual evaluation attempts, conversation trajectories, and tool execution.
3. **EventEmitter (`events.py`)**: A centralized bus that emits state transitions. 
4. **Plugins (`plugins.py`)**: Flexible hooks that can observe or intercept core behavior.

### 3.2 Immutability
`EvaluationContext` and `TurnContext` are **frozen** dataclasses. You cannot modify them directly inside hooks; instead, use `dataclasses.replace` if you need to pass a modified state upstream.

### 3.3 Agent Adapter (Ecosystem Hub)
Default: HTTP POST to `AGENT_API_URL`.
The harness uses an **Adapter Pattern** to support diverse providers and frameworks. Using the `on_discover_adapters` hook, you can register custom protocols (e.g., `openai://`, `gemini://`, `custom://`).

#### 🛠️ Tutorial: Building a Custom Adapter
To add a new provider, create a plugin that implements the `on_discover_adapters` hook.

```python
from eval_runner.plugins import BaseEvalPlugin
import aiohttp

class MyProviderPlugin(BaseEvalPlugin):
    def on_discover_adapters(self, registry):
        # Register the protocol scheme
        registry.register("myproto", self.execute_task)

    async def execute_task(self, payload: dict) -> dict:
        # payload contains: task, messages, tools, etc.
        async with aiohttp.ClientSession() as session:
            # Implement your API call logic here
            return {
                "status": "success",
                "output": "Agent response text",
                "metadata": {"model": "my-model-v1"}
            }
```

Register this plugin in your `pyproject.toml` or load it via the `PluginManager` to enable `myproto://` URLs in AES scenarios.

---

## 🔌 4) Plugin System

Plugins are the primary extension point. They are discovered via `eval_runner.plugins` entry points in `pyproject.toml`.

### 4.1 Lifecycle Hooks
| Hook | Purpose |
|---|---|
| `before_evaluation` | Global setup or config validation. |
| `on_agent_turn_start`| Pre-inspect the context before the agent speaks. |
| `on_tool_request` | **Interception**: Return `False` to block a tool call. |
| `on_tool_result` | Observe tool outputs and world state side-effects. |
| `on_metrics_calculated`| Post-process or inject custom metrics. |
| `on_register_commands` | Securely register plugin CLI commands (replaces `extend_cli`). |
| `on_register_console_routes` | Inject custom REST routes and React Native Expo UI navigation links. |
| `after_evaluation` | Final reporting or post-run notifications. |

### 4.2 Interception Example
Plugins can block tools based on safety policies or human-in-the-loop triggers:
```python
def on_tool_request(self, context: TurnContext, tool_name: str, args: dict) -> bool:
    if tool_name == "delete_all" and not args.get("confirmed"):
        return False # Blocks the call
    return True
```

### 4.3 Extending the Web Admin Console (Native GUI)
Enterprise plugins can inject their own user interfaces natively into the `eval-harness console` Expo application using a **Secure Handoff** architecture.

#### Secure Handoff Workflow:
1. **JWT Issuance**: The frontend requests a short-lived (60s) handoff token from `/api/auth/handoff`.
2. **Authentication**: The plugin route must be decorated with `@handoff_required` to verify this token.
3. **Dual Rendering Modes**:
   - **Mode A (Native SDUI)**: If the endpoint returns `application/json` with a UI spec, the console renders it using native React Native components.
   - **Mode B (Secure WebView)**: If it returns HTML, the console renders an authenticated WebView.

```python
from flask import Blueprint, jsonify
from eval_runner.console.auth import handoff_required

class EnterpriseConsolePlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        # 1. Register link with 'type' metadata ('internal' | 'external' | 'plugin')
        nav_registry.append({
            "id": "compliance_audit", 
            "title": "Compliance Audit", 
            "path": "/api/enterprise/audit", 
            "icon": "shield",
            "type": "plugin"
        })
        
        # 2. Register Secure Blueprint
        bp = Blueprint("enterprise", __name__)
        
        @bp.route("/api/enterprise/audit")
        @handoff_required
        def audit_view():
            # Mode A: Server-Driven UI (Native)
            return jsonify({
                "title": "Enterprise Audit",
                "items": [
                    {"label": "PII Leakage", "value": "0 Detected"},
                    {"label": "Sanitization", "value": "100% Pass"}
                ]
            })
            
        app.register_blueprint(bp)
```

---

## 📡 5) VS Code Extension & IDE Integration

The harness now includes a **VS Code Extension** scaffold (`vscode-extension/`) that brings core evaluation workflows directly into the editor.
- **Run Scenario**: Right-click any `.json` scenario to execute a trace.
- **Open Console**: One-click access to the Web Admin Console.

---

## 🛠️ 6) Visual Scenario Editor (AES Builder)

The `admin-console/app/editor.tsx` provides a visual playground for constructing complex evaluation logic. Developers can add task nodes and validation expectations via a drag-and-drop interface, which then generates the underlying AES JSON.

---

## 📡 7) Event-Driven Monitoring

The `EventEmitter` allows you to build observability without touching the core code.

```python
from eval_runner.events import EventEmitter, CoreEvents

@EventEmitter.on(CoreEvents.TOOL_CALL)
def audit_logger(payload):
    print(f"Audit: {payload['tool']}({payload['arguments']})")
```

---

## 📊 6) Metrics System

Metrics live in `eval_runner/metrics.py`. Register a new metric:
```python
from eval_runner.metrics import MetricRegistry

def my_score(criterion, summary):
    return 1.0 if "pass" in summary else 0.0

MetricRegistry.register("my_score", my_score)
```

---

## 🤝 7) Contribution Flow
1. Add scenario JSON in `industries/<industry>/scenarios/`.
2. Run with `eval-harness run <path>`.
3. Add specialized metrics or plugins as needed.
4. Verify with `pytest tests/`.

---

For internal logic of utilities like `doctor` or `quickstart`, see the corresponding files in `eval_runner/`.
