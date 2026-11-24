---
title: World Shimming
description: Guide to environment simulators for stateful, high-fidelity agent evaluation.
---

World shims implement stateful test environments. Register a simulator class,
then explicitly enable it in the scenario and allow it through the global gate.

## Implement the complete tool name

The sandbox routes a tool by its shim prefix and passes the entire tool name to
`BaseSimulator.execute`. That method looks up `handle_<complete_tool_name>`:

```python
from eval_runner.plugins import BaseEvalPlugin
from eval_runner.simulators import BaseSimulator


class IndustrialIoTSimulator(BaseSimulator):
    def handle_industrial_iot_read_sensor(self, params: dict) -> dict:
        self.state["sensor_active"] = True
        return {"status": "success", "payload": {"reading": 42}}


class MyShimPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry: dict):
        registry["industrial_iot"] = IndustrialIoTSimulator
```

The sandbox instantiates the registered class with `config=shim_cfg`. Dynamic
guest data belongs under `payload`: `ShimResultProxy` only exposes its allowed
guest keys (`status`, `message`, stdout/stderr, returncode, cwd and payload).
Private forensic metadata belongs in the secure metadata channel.

Add this root fragment to a valid AES scenario:

```json
{"enabled_shims": ["industrial_iot"]}
```

Call `industrial_iot_read_sensor` with `tool_name` / `tool_params`. The source
scenario remains the declarative contract; register the plugin through
`agentv_runtime.plugins` or the persistent plugin registry.

## Middleware and lifecycle

`SimulatorMiddleware.process_action(simulator, action, params, next_call)` wraps
dispatch. Register middleware with `sim.register_middleware(instance)`.
`quiesce()` settles asynchronous work before verification; the sandbox applies
a five-second timeout. Cleanup releases simulator resources during teardown.

The built-in registry includes 20 simulators, such as git, database, terminal,
browser, CRM, Stripe and IoT. Their actions and state behavior are defined in
`eval_runner.simulators`; do not infer live external execution from a shim name.

## Activation

`GLOBAL_ENABLED_SHIMS=*` permits all registered names through the global gate;
`GLOBAL_ENABLED_SHIMS=git,api` permits only those names. An absent scenario list
activates relevant shims; a present list restricts activation to its names or `*`.
See [discovery](/evaluator/discovery/) for the exact policy.
