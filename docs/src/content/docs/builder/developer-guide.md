---
title: Developer Guide
description: Core architecture, internals, and extension patterns for AgentV engineers.
---

This guide is for engineers building on or extending the AgentV harness.

## 📂 Repository Architecture

- **`eval_runner/`**: The core Python execution package. Includes the CLI dispatcher, orchestration engine, loaders, metrics, and simulators.
- **`agentv_runtime/`**: Public canonical runtime contracts, RFC 8785 JSON Canonicalization Scheme (JCS), and offline packaging primitives. This is an API boundary, not a dependency-free package: its public imports include cryptography, and reference implementations re-export eval_runner.
- **`dataproc_engine/`**: High-throughput telemetry stream processing and analytics pipeline.
- **`ui/visual-console/`**: High-density React ^19.2.8 + TypeScript Visual Console for interactive scenario authoring, trajectory inspection, and debugger graphs.
- **`vscode-extension/`**: Visual Studio Code extension providing AES schema validation and scenario authoring assistance.
- **`industries/`**: Industrial scenario library and golden evaluation benchmarks across finance, healthcare, telecom, and security.
- **`.aes/`**: Authoritative configuration mesh (Shims, Adapters, Forensics, and Key Vault).
- **`reports/`**: Destination for generated HTML and JSON verification reports and certificates.
- **`runs/`**: The Flight Recorder storage for isolated `.jsonl` execution vaults.
- **`tests/`**: Multi-tiered test suite (Unit, Integration, Functional, Security, Contracts, Golden, and Acceptance).
- **`tools/ci/`**: Sentinels, dependency compliance verification, AST mutation testing engine, and acceptance release gate.

---

## 🧠 Core Engine (Zero-Touch)

The engine is built on a decoupled, event-driven architecture to support enterprise-grade extensibility.

### Key Components
1.  **Runner (`runner.py`)**: Entry point for execution loops and multi-attempt (`pass@k`) logic.
2.  **SessionManager (`session.py`)**: Individual attempt state, trajectory tracking, and tool execution.
3.  **AgentAdapterRegistry**: Dynamic discovery of agent protocols (`http`, `langgraph`, `crewai`, etc.).
4.  **ToolSandbox**: Managed execution environment with workspace lifecycle management.
5.  **VerificationService (`verifier.py`)**: Manages `TraceVerificationInterceptor` chains for trace signing and validation.
6.  **ToolSandboxService (`tool_sandbox.py`)**: Context-isolated registry for `ToolSandboxInterceptor` execution filters.
7.  **MutationService (`mutator.py`)**: Manages `ScenarioMutator` chains for adversarial scenario variant generation.

### Immutability & Context Safety
*   `EvaluationContext` and `TurnContext` are **frozen** dataclasses. Interceptors must use `dataclasses.replace` to propagate state changes.
*   **Asynchronous Isolation**: `ToolSandboxService` leverages `contextvars.ContextVar` to secure coroutine-local state, ensuring concurrent evaluations remain safely isolated.
*   **Testing Helpers**: Pipeline services provide temporary override context managers (`override_interceptor` / `override_provider`). These temporarily activate a mock or custom interceptor/provider and guarantee clean, atomic state restoration on exit:
    ```python
    # In an async test or caller:
    async def exercise_sandbox():
        async with tool_sandbox_service.override_interceptor(my_mock_interceptor):
            return await sandbox.execute("git_commit", {"message": "example"})

    # Overriding mutations temporarily:
    with mutation_service.override_provider(my_custom_mutator):
        mutated = mutate_scenario(scenario, "custom_mode")
    ```

---

## 🔌 Plugin System

Plugins are the primary extension point for the harness.

### Lifecycle & Interceptor Hooks
| Hook | Purpose |
| :--- | :--- |
| `before_evaluation` | Global setup, span tagging, and configuration validation. |
| `after_evaluation` | Post-run teardown, artifact export, and metric publishing. |
| `on_step_start` / `on_step_end` | Workflow DAG node activation and verdict capture. |
| `on_tool_request` | **Interception**: Return `True` to allow, `False` to block, or `{"arguments": {...}}` to replace tool parameters. |
| `on_before_commit` / `on_rollback`| State transition validation gate and compensating rollback execution. |
| `on_approval_preflight` | Reject an approval-capable node before external agent invocation. |
| `on_approval_request` | Pre-evaluation filter for human review requests (return `True` to allow or modified dict). |
| `on_approval_created` / `on_approval_resolved`| Durable Human-in-the-Loop approval lifecycle events. |
| `on_artifact_created`| Forensic evidence artifact commit listener (SOC 2 CC6.8). |
| `on_register_commands`| Declared compatibility hook; CLI registration uses `agentv_runtime.cli_extensions` entry points directly. |
| `on_discover_adapters`| Register custom agent communication adapters with the registry. |
| `on_register_simulators`| Inject custom environment World Shims into the simulator cache. |
| `on_discover_metrics`| Dynamically register custom metric functions. |
| `on_diagnose_failure`| Register custom failure analyzers with the forensic taxonomy engine. |
| `on_register_console_routes`| Inject custom REST routes and navigation tabs into the [Visual Console](/evaluator/user-manual/). |

Dynamic interceptor hooks also include `on_approval_resolution(context, approval_data)`
(decision filtering), `on_tool_result(context, tool_name, result)` (result filtering
before delivery), and `on_tool_delivered(context, tool_name, result)` (notification
after the delivery/history boundary). These are invoked by name and are not
declared BaseEvalPlugin methods. A result interceptor can reject with `False` or
replace a result with `{"result": ...}`. Event-bridge callbacks can share names;
accept the relevant positional arguments and event keyword payloads when
implementing both paths. See [hooks](/extender/hooks/).

*(Note: Additionally, all `CoreEvents` emitted over the session event bus automatically bridge to `on_<event_name.lower()>(self, context, **event_data)` hooks on loaded plugins).*

---

## ⚖️ Metrics System

Metrics live in `eval_runner/metrics/` and are registered via the `MetricRegistry`.

### Registering a New Metric
```python
from eval_runner.metrics import MetricRegistry


@MetricRegistry.register("my_industrial_metric", source="EXTERNAL_PLUGIN")
def my_metric(criterion: dict, agent_summary: str, turns_taken: int) -> float:
    # Logic to return 0.0 to 1.0
    if turns_taken > 5:
        return 0.5
    return 1.0 if "success" in agent_summary else 0.0
```

### Parameter Introspection & Fulfillments
The core engine evaluates metrics using dynamic dispatch. It inspects your metric function's signature and automatically satisfies requested parameters. Available parameters include:
*   `criterion` / `eval_context`: The specific assertion metadata.
*   `agent_summary` / `summary` / `actual`: The agent's final text answer.
*   `conversation_history` / `history`: Deep-copied list of trajectory turns.
*   `used_tools` / `actual_tools`: List of tools execution trace.
*   `turns_taken`: Number of steps executed in this run.

---

## 🛡️ Sandbox & Workspace Lifecycle

The `ToolSandbox` ensures that each evaluation run has a clean, isolated environment.
- **`setup()`**: Creates `workspace/<run_id>` by default.
- **`teardown()`**: Deletes the workspace only when `cleanup_workspace` is explicitly true (metadata override or root field).

---

## 🔐 Security & Integrity

The harness uses an **Ed25519 / PQC (ML-DSA-65) asymmetric signing protocol** and **SHA3-256 canonical hashing** for non-repudiable audit trails.
- **Key Storage**: Keys are stored in `.aes/keys/`.
- **Execution Manifests**: Every run generates an authoritative, immutable [`ExecutionManifest`](/extender/api-reference/) binding scenario hash (`sha3_256`), runtime configuration, environment parameters, and agent configuration.
- **Manifests & Certificates**: Execution records the manifest/finalization; eligible runs require a separate `agentv certify` operation to issue a certificate. Undeclared execution mode defaults to simulated.
- **Gating**: Use `agentv gate` in the CI/CD pipeline to enforce signature verification and safety floor adherence.

### Tamper-evident audit trail sealing

The bound RunStorageProvider commits trace bytes. Event `_sig` fields depend on
the recorder's signer configuration; the recorder does not create a universal
previous-event hash chain or `audit_chain.jsonl` file. Certification binds the
exact trace and evidence commitments with current digest-envelope signatures.
Local logical seals detect tampering; physical WORM requires external retention.
