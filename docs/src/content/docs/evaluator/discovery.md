---
title: Authoritative Discovery Engine
description: Understanding shim activation policies, strict relevance, and environment discovery in AgentV v1.6.0.
---

The **Authoritative Discovery Engine** is a core component of the AgentV v1.6.0 industrial architecture. It ensures that only necessary and sanctioned simulators (shims) are activated during an evaluation, minimizing the forensic surface area and preventing unauthorized tool execution.

## 1. Activation Hierarchy

AgentV uses a multi-tier activation policy to determine which shims should be instantiated in the `ToolSandbox`.

| **1** | **Master Gate (Global)** | **Mandatory Hard Gate**. Controlled by `GLOBAL_ENABLED_SHIMS`. If a shim is blocked here, it is never activated. |
| **2** | **Forensic Relevance** | Activated if globally allowed AND explicitly targeted in the scenario's `expected_outcome` or `success_criteria`. |
| **3** | **Scenario Enablement** | Activated if globally allowed AND listed in the scenario's `enabled_shims` array. |

---

## 2. Capabilities vs. Shim Activation

It is important to distinguish between **Agent Capabilities** and **Shim Activation**:

- **Capabilities** (`metadata.capabilities`): High-level metadata (e.g., `sql_generation`, `api_integration`) used for agent selection and capability-based routing. These do **not** trigger shim activation.
- **Shim Activation**: Driven strictly by the Activation Hierarchy above. A shim is only provisioned if it is forensically relevant to the contract or explicitly enabled.

*Example*: Listing `sql_generation` in capabilities will not activate the `database` shim. You must either use a `database_` tool or mention a `shim:database` outcome to trigger activation.

### Strict vs. Permissive Mode

The engine operates in two modes based on the scenario configuration:

- **Strict Discovery Mode**: Triggered when `enabled_shims` is explicitly provided in the scenario (even if empty `[]`). Only relevant or explicitly listed shims are activated.
- **Legacy Permissive Mode**: Triggered when `enabled_shims` is missing. The engine activates all shims sanctioned by the `GLOBAL_ENABLED_SHIMS` policy to maintain backward compatibility.

---

## 2. Forensic Relevance Engine

The Discovery Engine scans the scenario's **Task Workflow** to identify shims required for contract verification.

```json
{
  "workflow": {
    "nodes": [
      {
        "id": "task_1",
        "expected_outcome": {
          "target": "shim:database:query_result",
          "value": "..."
        }
      }
    ]
  }
}
```

In the example above, the `database` shim is automatically flagged as **Relevant** and will be activated even if not explicitly listed in `enabled_shims`.

---

## 3. Registry & Type Resolution

The engine resolves shim identities across the **Authoritative Registry**:

1.  **Baseline Shims**: Internal simulators provided by the `eval_runner.simulators` package (e.g., `git`, `api`, `filesystem`).
2.  **Extended Shims**: Configured via `.aes/config/shims.d/` JSON files.
3.  **Plugin Shims**: Dynamically injected via the `on_register_simulators` plugin hook.

### Type Overrides
You can alias shims to use specific simulator classes via the `type` property in the registry:

```json
{
  "shims": {
    "proprietary_db": {
      "type": "database",
      "resources": { "url": "..." }
    }
  }
}
```
The `proprietary_db` shim will be instantiated using the built-in `DatabaseSimulator` class with custom resources.

---

## 4. Troubleshooting Discovery

If a tool call fails with "Shim not activated," follow these steps:

1.  **Check Scenario Contract**: Ensure the shim is mentioned in `expected_outcome` or added to `enabled_shims`.
2.  **Check Global Policy**: Verify that `GLOBAL_ENABLED_SHIMS` in `eval_runner/config.py` is not blocking the shim.
3.  **Run Doctor**: Execute `agentv doctor` to verify that the registry is correctly indexing your shim configurations.
