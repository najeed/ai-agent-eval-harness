---
title: World Shimming
description: Guide to environment simulators for stateful, high-fidelity agent evaluation.
---

World Shims are VFS-aware environment simulators that allow agents to interact with realistic, stateful systems without touching production infrastructure.

## 🚀 The Enterprise Suite (20 Built-in Shims)

The harness ships with a comprehensive suite of 20 shims covering common industrial and infrastructure domains.

| Category | Shims | Examples Actions |
| :--- | :--- | :--- |
| **Infrastructure** | `git`, `api`, `database`, `terminal`, `cloud` | `git_commit`, `database_query`, `cloud_launch` |
| **Communication** | `slack`, `email`, `jira`, `social`, `support` | `slack_send`, `jira_update`, `email_list` |
| **Business** | `crm`, `erp`, `stripe`, `calendar` | `crm_update_lead`, `stripe_charge`, `calendar_book` |
| **AI & Web** | `browser`, `vector`, `kb`, `cicd`, `iot`, `security` | `browser_go`, `vector_query`, `iot_control` |

---

## 🏗️ How Shims Work (VFS Parity)

Shims integrate directly with the **Virtual File System (VFS)** to ensure forensic state parity:

1.  **Sandbox State**: The `ToolSandbox` maintains a `.state` dictionary.
2.  **Routing**: When an agent calls a tool (e.g., `database_query`), the sandbox routes it to the correct shim.
3.  **Reflection**: The shim executes the action and returns `state_changes` which are applied to the VFS.
4.  **Parity Check**: At the end of a run, the engine compares the VFS state against the **Ground Truth** defined in the scenario.

---

## 🛠️ Adding a Custom Shim

You can add new shims via the [Plugin System](/extender/plugins/) to keep the core immutable.

### 1. Define the Simulator
Create a class that inherits from `BaseSimulator` and implements the `async def execute(action, params)` interface. Action dispatching is handled automatically via handler methods (e.g. `handle_<action>`).

```python
from eval_runner.simulators import BaseSimulator

class IndustrialIoTSimulator(BaseSimulator):
    async def execute(self, action: str, params: dict) -> dict:
        # Middleware pipeline triggers automatically.
        # Delegates internally to handle_<action> methods.
        return await super().execute(action, params)

    def handle_read_sensor(self, params: dict) -> dict:
        # State logic here
        self.state["sensor_active"] = True
        return {"status": "success", "reading": 42}
```

### 2. Register via Plugin Hook
Override the `on_register_simulators` hook in your plugin.
```python
from eval_runner.plugins import BaseEvalPlugin

class MyShimPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry: dict):
        registry["industrial_iot"] = IndustrialIoTSimulator()
```

### 3. Registering Middleware
You can register custom `SimulatorMiddleware` classes on simulator instances to intercept actions (for network latency injection, rate limiting, or logging):
```python
sim = IndustrialIoTSimulator()
sim.register_middleware(LatencySimulationMiddleware())
```

### 4. Configure via Hybrid Registry
Add your shim configurations to the [Cumulative Registry](/extender/api-reference/) (`shim_resources.json`) to decouple URLs and credentials from logic.

---

## ⚙️ Configuration & Activation

### Per-Scenario Activation
Enable specific shims by adding them to your scenario JSON:
```json
{
  "id": "iot_test",
  "enabled_shims": ["database", "industrial_iot"]
}
```

### Global Override (The Master Gate)
Use the `GLOBAL_ENABLED_SHIMS` environment variable to restrict available shims system-wide. This acts as a **Hard Gate**: if a shim is blocked globally, it cannot be activated by any scenario.
- `GLOBAL_ENABLED_SHIMS=*` (Enable all sanctioned shims)
- `GLOBAL_ENABLED_SHIMS=git,api` (Restrict system to Git and API only)
