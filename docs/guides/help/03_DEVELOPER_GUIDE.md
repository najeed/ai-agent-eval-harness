# 🛠 Developer Guide — MultiAgentEval

This guide is for engineers building on or extending the harness.

---

## 📂 1 Repository Overview

**Key directories:**
- `eval_runner/` — Core engine, loaders, metrics, reporter, plugins, simulators, CLI
- `industries/` — Industry scenario libraries
- `reports/` — Generated evaluation artifacts (JSON, trajectories, heatmaps)
- `runs/` — Recorded execution traces (`run.jsonl`)
- `docs/guides/help/` — Documentation for users and contributors
- `tests/` — Unit & integration tests

---

## 🧩 2 CLI Architecture

Entry point: `eval_runner/cli.py`

### Main commands
- `evaluate` — Run a batch of scenarios
- `quickstart` — End-to-end evaluation demo using `sample_agent`
- `console` — Launch the Integrated Visual Suite backend (with background execution and live visual debugging)
- `doctor` — Validate environment health and dependencies
- `init` — Scaffold new project directories with synthetic datasets
- `report` — Generate a standalone **Premium HTML report** (reconstructed from any `.jsonl` trace)
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

## 🧠 3 Evaluation Engine (Zero-Touch Core)

The core has been refactored into a decoupled, event-driven architecture to support Enterprise hot-swapping.

### 3.1 Architectural Components
1. **Runner (`runner.py`)**: Orchestrates the high-level evaluation loop, handling multi-attempt (`pass@k`) logic.
2. **SessionManager (`session.py`)**: Manages individual evaluation attempts, conversation trajectories, and tool execution.
4. **AgentAdapterRegistry** (`adapter_registry.py`): Dynamically discovers and registers agent protocols at runtime.
5. **Plugins (`plugins.py`)**: Flexible hooks that can observe or intercept core behavior.
6. **ToolSandbox (`tool_sandbox.py`)**: Managed execution environment with automated workspace lifecycle.
7. **Loader & Catalog (`loader.py`, `catalog.py`)**: Support for **Path Decoupling**, enabling scenarios to be loaded from any location with relative dataset resolution and automatic industry tagging (`local`, `unclassified`).

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

## 🔌 4 Plugin System

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
| `on_register_console_routes` | Inject custom REST routes and React Visual Suite navigation links. |
| `after_evaluation` | Final reporting or post-run notifications. |

### 4.2 Interception Example
Plugins can block tools based on safety policies or human-in-the-loop triggers:
```python
def on_tool_request(self, context: TurnContext, tool_name: str, args: dict) -> bool:
    if tool_name == "delete_all" and not args.get("confirmed"):
        return False # Blocks the call
    return True
```

### 4.3 Extending the Integrated Visual Suite (Native GUI)
The Visual Suite uses a **Secure Handoff** architecture and provides integrated high-level features like the **Visual Scenario Editor** (persists directly to disk) and the **Visual DNA Debugger** (taps into engine events).

#### Secure Handoff Workflow:
1. **JWT Issuance**: The frontend requests a short-lived (60s) handoff token from `/api/auth/handoff`.
2. **Authentication**: The plugin route must be decorated with `@handoff_required` to verify this token.
3. **Dual Rendering Modes**:
   - **Mode A (Native SDUI)**: If the endpoint returns `application/json` with a UI spec, the console renders it using native React components.
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
```

---

## 📡 5 VS Code Extension & IDE Integration

The harness now includes a **VS Code Extension** scaffold (`vscode-extension/`) that brings core evaluation workflows directly into the editor.
- **Run Scenario**: Right-click any `.json` scenario to execute a trace.
- **`Visual Debugger`**: The premium React UI for visualizing results.

---

## 🛠️ 6 Visual Scenario Editor (AES Builder)

The Integrated Visual Suite provides a visual playground for constructing complex evaluation logic. Developers can add task nodes and validation expectations via a drag-and-drop interface, which then generates the underlying AES JSON.

---

## 📡 7 Event-Driven Monitoring

The `EventEmitter` allows you to build observability without touching the core code.

```python
from eval_runner.events import EventEmitter, CoreEvents

@EventEmitter.on(CoreEvents.TOOL_CALL)
def audit_logger(payload):
    print(f"Audit: {payload['tool']}({payload['arguments']})")
```

---

## 📊 8 Metrics System

Metrics live in the `eval_runner/metrics/` package. 

### 8.1 State Verification (Nested Paths)
The `calculate_state_correctness` metric supports **dot-notation** for deep object inspection. This is implemented via the `get_nested_value` utility, which recursively traverses dictionaries.

### 8.2 Judge Guarding
Metrics using `calculate_luna_judge_score` can now specify a `required: true` flag. 
- **Behavior**: If a required judge provider fails to initialize (e.g., missing API key or unknown provider), the engine raises a `RuntimeError` (wrapped as a `JudgeConfigurationError` in the UI).
- **Fallback**: If not required, the engine logs a warning and falls back to **Jaccard similarity** to prevent crashing the evaluation.

### 8.3 Hardened Metric Loop
The `SessionManager` now wraps metric calculations in a try-except block. A single malformed metric or a transient failure during judging will no longer terminate the entire multi-scenario run.

Register a new metric:
```python
from eval_runner.metrics import MetricRegistry

@MetricRegistry.register("my_score")
def my_score(criterion, summary):
    return 1.0 if "pass" in summary else 0.0

# Ensure the module containing this function is imported in eval_runner/metrics/__init__.py
```

---

## 🛠️ 9 Sandbox Workspace Lifecycle

The `ToolSandbox` now supports automated environment management via lifecycle hooks:

### 9.1 Setup & Teardown
- **`setup()`**: Initializes a fresh workspace directory (under `workspaces/`) for the scenario.
- **`teardown()`**: Cleans up the workspace directory after execution.

### 9.2 Configuration
Cleanup is conditional based on the scenario metadata:
```json
{
  "scenario_id": "example-123",
  "metadata": {
    "cleanup_workspace": true
  }
}
```
If `cleanup_workspace` is `false` (default for many research scenarios), the directory is preserved for forensic analysis.

---

## 🤝 10 Contribution & Verification Flow
1. Add scenario JSON in `industries/<industry>/scenarios/`.
2. Run with `multiagent-eval run --scenario <path>`.
3. Add specialized metrics or plugins as needed.
4. Coverage Standard: All new core utilities must target 90%+ coverage.
5. Verification: Run the full suite with `pytest tests/`.
6. Linting: Ensure compliance with `flake8` standards.

---

## 🔐 11 Extending Authentication & PBAC

The MultiAgentEval console uses an extensible **Auth Provider Pattern**. This allows the harness to stay "Zero-Touch" for local development while providing a clean hook for Enterprise SSO and PBAC integration.

### 11.1 AuthManager Abstraction
The core auth logic is defined in `eval_runner/console/auth_manager.py`.

- **`AuthManager` (Base)**: An abstract interface for `authenticate()` and `has_permission()`.
- **`StaticKeyProvider` (Default)**: Uses the `DASHBOARD_API_KEY` environment variable as a Root/Master credential, mapping automatically to the full set of PBAC nodes.

### 11.2 Implementing Custom SSO/PBAC
To integrate with an Enterprise Identity Provider (e.g., Okta, Azure AD, Ping), subclass `AuthManager` and override the factory method in `auth_manager.py`:
### 11.2 Extending Authentication & PBAC

For enterprise/SaaS scenarios, the `AuthManager` can be replaced with a custom provider (e.g., Okta, Azure AD).

1. **Subclass AuthManager**: Implement `authenticate` and `has_permission` using granular permission strings.
2. **Permission Mapping**: Map your external identity claims (e.g., JWT groups) to harness permission nodes (e.g., `Role.EVAL_TRIGGER`).
3. **Custom Nodes**: Enterprise plugins can define their own strings (e.g., `governance:report:export`) to protect their unique API endpoints.

```python
from .auth_manager import AuthManager, Role

class OktaAuthProvider(AuthManager):
    def authenticate(self, token: str):
        # 1. Verify JWT with Okta
        # 2. Extract 'groups' or 'roles' claims
        return {
            "id": "user@org.com",
            "permissions": [Role.SCENARIOS_READ, Role.EVAL_TRIGGER] 
        }

    def has_permission(self, user: dict, permission_node: str):
        # In PBAC, check if the specific node is authorized
        return permission_node in user.get("permissions", [])
```

### 11.3 Protecting Routes
Use the `@require_permission` decorator in `routes.py` with granular nodes:

```python
from .auth_manager import Role
from .auth_manager import require_permission # Re-imported from manager in routes.py

@core_bp.route("/admin/settings")
@require_permission(Role.SYSTEM_CONFIG)
def admin_settings():
    return "Sensitive Data"
```

---

## 🔐 12 Security & Artifact Integrity

The harness uses an **ED25519-based signing protocol** to ensure the integrity of evaluation artifacts.

### 12.1 Signing Workflow
- **Key Generation**: If `AES_PRIVATE_KEY` is missing from `.env`, the engine auto-generates a key in `.aes/keys/`.
- **Manifest Signing**: The `ArtifactPlugin` generates an `audit_manifest.json` for every run, containing hashes of all traces and reports, signed by the system's private key.
- **Verification**: Use `multiagent-eval verify --path <trace>` to validate the signature against the public key.

### 12.2 CI/CD Hard Gates
The `gate` command enforces these signatures in pipeline environments, preventing unverified or tampered results from passing the build.

---

## 🏗️ 13 JIT-Babel UI Hydration

Custom UI modules (Story Demos, Adversarial Visualizations) are loaded dynamically via JIT-Babel. To ensure these modules can interact with the protected API, they **must** follow the hydration (UI loading) protocol.

### 13.1 The `apiFetch` Prop
Every custom component rendered by the Visual Suite receives an `apiFetch` prop. This is a pre-configured, authenticated `fetch` wrapper that includes the necessary PBAC headers.

**Requirement**: Do NOT use raw `fetch` or `axios` in custom modules. Always use the provided prop.

```jsx
const MyCustomDemo = ({ apiFetch }) => {
    const [data, setData] = React.useState(null);

    React.useEffect(() => {
        // Use the authenticated wrapper provided by the suite
        apiFetch("/api/my-data")
            .then(res => res.json())
            .then(setData);
    }, [apiFetch]);

    return <div>{data ? "Loaded" : "Loading..."}</div>;
};
```

### 13.2 Embedding the Debugger
If your custom module embeds the `VisualDebugger`, you **must** propagate the `apiFetch` prop to it:

```jsx
<VisualDebugger 
    runId="my-run-id" 
    apiFetch={apiFetch} 
/>
```

Failure to propagate this prop will result in `401 Unauthorized` errors when the debugger attempts to fetch trace events.

---

## 🌐 14 JIT Hydration & Story Modules

The Visual Suite uses **JIT-Babel** to dynamically load React components (Story Modules) like `Demo.jsx` or `LoanDemo.jsx`.

### 14.1 `window.apiFetch`
Because the backend uses **Permission-Based Access Control (PBAC)**, standard `fetch` calls from Story Modules will fail with a 401/403.
- All Story Modules **MUST** use `window.apiFetch`.
- `apiFetch` automatically injects the necessary security headers and handles the auth-refresh handshake.

---

For internal logic of utilities like `doctor` or `quickstart`, see the corresponding files in `eval_runner/`.
