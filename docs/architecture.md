# Architecture Overview

This document describes the system architecture of the AI Agent Evaluation Harness, following the "Visionary Core 2.0" evolution.

## High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             CLI (eval_runner/cli.py)                        │
│  • evaluate / import-drift / aes validate / replay                          │
└──────────────┬───────────────────┬────────────────────────┬─────────────────┘
               │                   │                        │
               ▼                   ▼                        ▼
┌───────────────────────────┐  ┌──────────────────────┐  ┌───────────────────────┐
│     Loader (loader.py)    │  │  AES Spec (/spec)    │  │  Drift (drift_imp...) │
│ • Universal Registry      │  │ • Schema Validation  │  │ • Production Traces   │
│ • JSON v2 / CSV / JSONL   │  │ • Portable Benchmarks│  │ • Scenario Conversion │
└──────────────┬────────────┘  └──────────┬───────────┘  └──────────┬────────────┘
               │                          │                         │
               └──────────────────────────┼─────────────────────────┘
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Engine (eval_runner/engine.py)                   │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │     Multi-turn Conversation Loop (with hooks)                          │ │
│  │  [before_evaluation] -> [on_turn_end] -> [after_eval]                  │ │
│  └───────────────────────────────────┬────────────────────────────────────┘ │
│                                      │                                      │
│  ┌───────────────────────────┐       ▼        ┌──────────────────────────┐  │
│  │ Metrics (metrics.py)      │◀─────────────▶│ Tool Sandbox (sandbox.py)│  │
│  │ • Pluggable Logic         │                │ • Governance Policies    │  │
│  │ • Path Efficiency         │                │ • SharedStateRegistry    │  │
│  └───────────────────────────┘                └──────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────────────────┘
                       │ 
                       ▼ 
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Persistence & Reporting                            │
│                                                                             │
│  • run.jsonl (Flight Recorder): Deterministic, streamable execution logs    │
│  • trajectories/: Mermaid visual flows for debugging                        │
│  • triage.py: Heuristic failure tagging (CONNECTION_ERROR, etc.)            │
│  • coverage/: HTML grounding heatmaps                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Inventory

| Module | File | Purpose |
|--------|------|---------|
| CLI | `eval_runner/cli.py` | Universal entry-point (`replay`, `aes`, `import-drift`) |
| Loader | `eval_runner/loader.py` | Multi-format dataset ingestion and v2.0 schema validation |
### `EventEmitter` Bus: Passive Observation
The core engine is built around a central `EventEmitter` (see `eval_runner/events.py`). Every state transition in the harness - from the start of a run to a tool call or an agent response - is emitted as an event. This allows plugins to observe the system's behavior without modifying the core logic.

#### Key Event Types:
- `RUN_START` / `RUN_END`: lifecycle of the entire evaluation.
- `TASK_START` / `TASK_END`: cycle for a specific scenario task.
- `PROMPT`: when the harness sends a request to the agent.
- `AGENT_RESPONSE`: when the agent returns an action.
- `TOOL_CALL` / `TOOL_RESULT`: execution of a sandbox tool.
- `HITL_PAUSE` / `HITL_RESUME`: Human-In-The-Loop events.

### Plugin Lifecycle
Plugins (inheriting from `BaseEvalPlugin`) hook into specific stages of the evaluation loop. The `PluginManager` triggers these hooks synchronously, ensuring a deterministic execution order.

| Hook | Trigger Point | Use Case |
|---|---|---|
| `on_run_start` | Before the evaluation starts | Setup monitoring or telemetry |
| `on_tool_request` | When an agent requests a tool | Interception, blocking, or masking |
| `on_discover_adapters` | During agent initialization | Register custom agent protocols |
| `on_eval_complete` | After metrics are calculated | Custom reporting or triage |
| Engine | `eval_runner/engine.py` | Minimal entry point for initializing the evaluation context |
| Runner | `eval_runner/runner.py` | Pluggable orchestration strategies (e.g., `DefaultRunner` for pass@k) |
| Session | `eval_runner/session.py`| Handles immutable turn-contexts and conversation state management |
| Event Hub | `eval_runner/events.py` | Centralized `EventEmitter` for decoupled, non-blocking observation |
| Plugin Manager | `eval_runner/plugins.py`| Robust lifecycle hooks and interception for Enterprise extensions |
| Tool Sandbox | `eval_runner/tool_sandbox.py`| Stateful mock executor with policy guardrails and observer signals |
| Reporting | `eval_runner/reporting_plugin.py`| Decoupled report generation (HTML/Console) and triage automation |
| Flight Recorder | `eval_runner/flight_recorder.py`| Passive event logger subscribing to the core event bus |
| Metrics | `eval_runner/metrics.py` | Research-grade scoring: Consenus, PII, and Consistency Scoring |
| Simulators | `eval_runner/simulators.py`| Deterministic tool shims (Git, API) for dependency-free testing |
| Mutator | `eval_runner/mutator.py` | Adversarial Mutation Engine for robustness red-teaming |
| Triage | `eval_runner/triage.py`| Heuristic failure pattern matching and tagging |
| Exporter | `eval_runner/exporter.py`| Conversion from internal `run.jsonl` to external formats (e.g., HuggingFace) |
| Benchmarks | `eval_runner/benchmarks/`| Native integrations for community datasets (GAIA, AssistantBench) |
| Adapters | `eval_runner/adapters/`| Native plugin shims for external frameworks (LangGraph, CrewAI) |

## Foundational Core: AES & Flight Recorder

Phase 1 establishes the "Standardized Evaluation" layer:
- **AES (Agent Eval Specification)**: A framework-agnostic YAML format defining agent tasks, expected states, and safety policies. It enables benchmark sharing across repositories.
- **`run.jsonl` (Flight Recorder)**: Every evaluation emits an append-only, deterministic log. This serves as the "source of truth" for replaying and debugging agent behavior without re-running the actual models.
- **Agent Crash Replayer**: The `replay` CLI command reconstructs the agent's timeline from a `run.jsonl` file, enabling step-by-step inspection.

## Semantic Bridge & Drift Management

Phase 2 focuses on operationalizing evaluation data:
- **Drift Management**: The `import-drift` command creates a "Semantic Bridge" between production behavior and evaluation rigor, allowing developers to quickly capture and fix real-world edge cases.
- **Edge-Case Triage**: A library of heuristics that automatically tags failed runs (e.g., `POLICY_VIOLATION`, `CONNECTION_ERROR`), drastically reducing manual debugging time.
- **Grounding Coverage**: Tracks the utilization of domain-specific tools and knowledge bases during execution, visualizeable via an HTML heatmap.

## Advanced Orchestration: HITL & Branching

Phase 3 introduces advanced orchestration capabilities for research and complex production replay:
- **Native HITL (Human-In-The-Loop)**: The `human` adapter allows scenarios to pause and wait for human intervention. This is integrated directly into the `SessionManager` loop, emitting `HITL_PAUSE` and `HITL_RESUME` events.
- **Non-Linear Trajectories**: `SessionManager.fork()` enables creators to explore multiple agent paths from a single checkpoint. This is essential for studying agent decision-making under ambiguity.
- **Advanced Adapter Discovery**: The `AgentAdapterRegistry` now supports plugin-driven discovery. External plugins can register custom protocols (e.g., `mock_proto`, `proprietary_rpc`) using the `on_discover_adapters` hook.

## Simulation Lab & Research metrics

- **Simulation Shims**: State-aware mocks (Git Simulator) that enable testing complex agentic tasks (clone -> hack -> commit) without real infrastructure.
- **Research Metrics**: Native support for `pass@k` (robustness across attempts) and `Success Consistency`.
- **Adversarial Red-Teaming**: The `mutator` engine injects typos, prompt-injection, and ambiguity into scenarios to test agent edge-resistance.

## Ecosystem, Benchmarks & Distribution

Phase 4 elevates the Harness from an isolated tool to an integrated participant in the open AI evaluation ecosystem:
- **Community Benchmark Integration**: The harness natively supports downloading and structuring data from major AI benchmarks. Passing URIs like `gaia://...` to the loader transparently fetches and wraps the datasets into executable `Scenario` objects with compatible metrics.
- **HuggingFace Distribution**: The `HFExporter` enables a one-click CLI flow (`eval-harness export --format hf`) to transform deterministic internal `run.jsonl` flight logs into normalized datasets ready for HuggingFace publication and leaderboards.
- **Framework Adapters via Plugins**: Supporting frameworks like `LangGraph` and `CrewAI` without "polluting" the core engine. These are implemented as modular `BaseEvalPlugin` classes that hook into the `on_discover_adapters` lifecycle to register their custom `langgraph://` or `crewai://` execution protocols.

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |

## Test Suite

15+ test files covering core engine, metrics, drift ingestion, and triage. Run with:
```bash
python -m pytest tests/ -v -p no:plugin_gateway
```

## Security Guardrails (Enterprise Audit)

The following mitigations are enforced at the core level:

| # | Threat | Mitigation | Location |
|---|---|---|---|
| 1 | DoS / CPU Exhaustion | `MAX_ENGINE_ATTEMPTS = 50` hard cap | `engine.py` |
| 2 | PII / Token Leakage | `sanitize_payload()` redacts JWT, AWS, GitHub, Bearer tokens and neutralizes format-string injection | `events.py` |
| 3 | CLI Command Hijacking | `extend_cli` removed; plugins use namespaced `on_register_commands` under `eval-harness plugin <name>` | `cli.py`, `plugins.py` |
| 4 | Plugin Halt (Hang) | All hooks wrapped in `PLUGIN_TIMEOUT = 5.0s` via `_invoke_with_timeout()` | `plugins.py` |
| 5 | Sandbox Escape | Chroot on emitted state keys **and** values; shell meta-characters (`;`, `\|`, `&&`, `` ` ``) stripped | `tool_sandbox.py` |
| 6 | Fork Bomb | `MAX_FORK_DEPTH = 3`, `MAX_FORK_BREADTH = 5` enforced in `SessionManager` | `session.py` |
| 7 | RCE via Repro Scripts | Scripts output as inert `.txt`; `os.system`/`subprocess` strings stripped | `reporting_plugin.py` |
| 8 | Prototype Pollution | `EvaluationContext`/`TurnContext` are `frozen` dataclasses; nested dicts wrapped in `MappingProxyType`; history stored as `tuple` | `context.py` |

