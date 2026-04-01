The "Zero-Touch Core" is a design philosophy ensuring the central evaluation engine remains framework-agnostic. All industry-specific logic, communication protocols (adapters), and World Shims (Environment Simulators) are implemented as modular plugins.

## High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             CLI (eval_runner/cli.py)                        │
│  • evaluate / run / console / list / lint / taxonomy / drift / aes          │
└──────────────┬───────────────────┬────────────────────────┬─────────────────┘
               │                   │                        │
               ▼                   ▼                        ▼
┌───────────────────────────┐  ┌──────────────────────┐  ┌───────────────────────┐
│     Loader (loader.py)    │  │  AES Spec (/spec)    │  │ Drift (drift_importer)│
│ • Universal Registry      │  │ • DAG Workflows      │  │ • Production Traces   │
│ • Auto-Shim               │  │ • Typed Outcomes     │  │ • Scenario Conversion │
└──────────────┬────────────┘  └──────────┬───────────┘  └──────────┬────────────┘
               │                          │                         │
               └──────────────────────────┼─────────────────────────┘
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            Engine (eval_runner/session.py)                   │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │     DAG-Based Execution Loop (nodes/edges)                             │  │
│  │  [node_start] -> [turn_loop] -> [calculate_metrics] -> [node_end]      │  │
│  └───────────────────────────────────┬────────────────────────────────────┘  │
│                                      │                                       │
│  ┌────────────────────────────┐       ▼        ┌──────────────────────────┐  │
│  │ Metrics (/metrics)         │◀─────────────▶│ Tool Sandbox (sandbox.py)│  │
│  │ • Modular Category Modules │                │ • Governance Policies    │  │
│  │ • High-Fidelity Judging    │                │ • SharedStateRegistry    │  │
│  └────────────────────────────┘                └──────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────────────────────┘
                       │ 
                       ▼ 
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Persistence & Reporting                            │
│                                                                             │
│  • run.jsonl (Flight Recorder): Deterministic, streamable execution logs    │
│  • trajectories/: Mermaid visual flows (Reconstructed from traces)          │
│  • triage.py: Heuristic failure tagging (CONNECTION_ERROR, etc.)            │
│  • coverage/: HTML grounding heatmaps                                       │
│                                       │                                     │
│  • catalog/: Optimized scenario indexing and faceted search                 │
│  • linter/: AES compliance and quality scoring logic                        │
│  • dashboard/: SPA Frontend (Integrated Visual Suite)                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Inventory

| Module | File | Purpose |
|--------|------|---------|
| Integrated Visual Suite | `eval_runner/console/` & `ui/visual-debugger/` | Flask proxy API (Background Eval) and Unified React SPA |
| Rubrics | `eval_runner/rubrics.py` | Registry for industry-standard evaluation prompts |
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
Plugins (inheriting from `BaseEvalPlugin`) hook into specific stages of the evaluation loop. The `discovery` module (powered by `eval_runner/discovery.py`) identifies valid plugin classes in the project-root `/plugins` directory and package-local subdirectories.

The `PluginManager` triggers these hooks synchronously, ensuring a deterministic execution order.

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
| Metrics | `eval_runner/metrics/` | Modular, high-fidelity evaluators: Accuracy, Planning, and Defense |
| Simulators | `eval_runner/simulators.py`| World Shim suite (20+ simulators) for high-fidelity testing |
| Triage | `eval_runner/triage.py`| High-fidelity trajectory forensics and confidence-based root cause isolation |
| Visual Suite | `ui/visual-debugger/` | React Flow powered dashboard for real-time trajectory analysis |
| Analyzer | `eval_runner/analyzer.py`| Proactive GitHub repo scanning and AES scenario scaffolding |
| Explainer | `eval_runner/explainer.py`| Heuristic-based trace diagnostics and root cause analysis |
| Trace Verifier | `eval_runner/verifier.py` | Asymmetric signing and integrity verification (ED25519) |

## Regulatory Enforcement Layer: AES v1.2 & Dataproc Engine

AES v1.2 elevates the harness into a **Verification OS** for mission-critical industries, powered by the `dataproc_engine` simulation backbone:

- **Industrial Simulation Backbone (`dataproc_engine`)**: A high-fidelity data extraction and synthesis engine that powers 8 core industrial sectors:
    - **Finance**: ISO-20022 compliant transaction streams and credit risk models.
    - **Healthcare**: HL7 FHIR-mapped EHR simulations and PII-masked clinical records.
    - **Telecom**: Network topology logs and CDR (Call Detail Record) troubleshooting data.
    - **Energy**: Grid load signals and renewable energy optimization telemetry.
    - **Ecommerce**: SKU inventory states and multi-stage fulfillment workflows.
    - **Transportation**: Logistics routing manifests and real-time fleet telemetry.
    - **Agriculture**: IoT soil sensor data and supply chain traceability logs.
    - **Unstructured**: Raw document pools for testing "bare metal" extraction capabilities.

- **Zero-Touch Provider Discovery**: The `dataproc_engine` utilizes a dynamic discovery system. By placing a new provider in the `dataproc_engine/providers/` directory, it is automatically registered with the `DatasetEngine`, allowing scenarios to access new industrial data instantly without core modifications.

- **Modular Data Extraction**: Simulation data is completely decoupled from logic. Industry-specific datasets are stored in externalized `.json` and `.csv` files within the `industries/` directory, ensuring auditability and ease of updates.

- **Robust AES Serialization**: Integrated a specialized `AESJsonEncoder` across the flight recorder and session history. This handles non-standard types (Mocks, Paths, Datetimes) safely, preventing runtime crashes during high-concurrency industrial simulations.

- **State-Machine DAG**: Scenarios define a directed acyclic graph of `nodes` and `edges`, enabling non-linear state transitions and dependency gating.

- **Pluralistic Judging (IJA)**: Implements Inter-Judge Agreement metrics. Critical industrial evaluations require a "Judge Panel" consensus (at least 3 judges) with a configurable `ija_threshold`.

- **`run.jsonl` (Flight Recorder)**: Every evaluation emits an append-only, deterministic log. This serves as the "source of truth" for replaying and debugging agent behavior in regulated environments.

- **Asymmetric Trust Protocol (ED25519)**: Transitioning from simple SHA-256 integrity to full asymmetric cryptographic sealing. Traces are signed with private keys and verified via public keys, enabling non-repudiable audit trails across different environments.

## Semantic Bridge & Drift Management

Phase 2 focuses on operationalizing evaluation data:
- **Drift Management**: The `import-drift` command creates a "Semantic Bridge" between production behavior and evaluation rigor, allowing developers to quickly capture and fix real-world edge cases.
- **Edge-Case Triage**: A library of heuristics that automatically tags failed runs (e.g., `POLICY_VIOLATION`, `CONNECTION_ERROR`), drastically reducing manual debugging time.
- **Grounding Coverage**: Tracks the utilization of domain-specific tools and knowledge bases during execution, visualizeable via an HTML heatmap.

## Advanced Orchestration: HITL & Branching

Phase 3 introduces advanced orchestration capabilities for research and complex production replay:
- **Native HITL (Human-In-The-Loop)**: The `human` adapter allows scenarios to pause and wait for human intervention. This is integrated directly into the `SessionManager` loop, emitting `HITL_PAUSE` and `HITL_RESUME` events.
- **Non-Linear Trajectories**: `SessionManager.fork()` enables creators to explore multiple agent paths from a single checkpoint. This is essential for studying agent decision-making under ambiguity.
- **Universal Agent Adapters**: The `AgentAdapterRegistry` allows switching between `http`, `local` (subprocess), and `socket` protocols. High-level metadata is propagated from the CLI to ensure the correct communication shim is used.
- **Advanced Adapter Discovery**: The registry supports plugin-driven discovery. External plugins can register custom protocols using the `on_discover_adapters` hook. Discovery is deferred until execution to maintain CLI performance.
- **Scenario Catalog & Intelligence**: A centralized indexer (`catalog.py`) enables high-performance discovery across thousands of scenarios. It supports keyword search and powers the Visual Suite "Scenario Explorer".
- **AES Quality Linter**: The `linter.py` module implements automated quality scoring, ensuring scenarios have required metadata, balanced task counts, and no duplicates.
- **Visual Debugger Hook**: A dedicated `DebuggerStateStore` in the console backend captures live world state and tool signals via the `EventEmitter` for real-time UI synchronization.

## Simulation Lab & Research metrics

- **High-Fidelity Metrics**: Decoupled framework with specialized modules for Calculation, Strategic Planning, and Causal Inference. Features robust numerical extraction, dynamic mock data loading from the `/industries` directory, and domain-specific LLM rubrics.
- **Research Metrics**: Native support for `pass@k` (robustness across attempts) and `Success Consistency`. The harness generates a `research_summary.md` and ASCII table for multi-attempt evaluations, capturing semantic stability and outcome variance.
- **Adversarial Red-Teaming**: The `mutator` engine injects typos, prompt-injection, and ambiguity into scenarios to test agent edge-resistance.

## Ecosystem, Benchmarks & Distribution

Phase 4 elevates the Harness from an isolated tool to an integrated participant in the open AI evaluation ecosystem:
- **Community Benchmark Integration**: The harness natively supports downloading and structuring data from major AI benchmarks. Passing URIs like `gaia://...` to the loader transparently fetches and wraps the datasets into executable `Scenario` objects with compatible metrics.
- **HuggingFace Distribution**: The `HFExporter` enables a one-click CLI flow (`multiagent-eval export --format hf`) to transform deterministic internal `run.jsonl` flight logs into normalized datasets ready for HuggingFace publication and leaderboards.
- **Framework Adapters via Plugins**: Supporting frameworks like `LangGraph`, `CrewAI`, and **Microsoft AutoGen** (via `autogen://`) without "polluting" the core engine. These are implemented as modular `BaseEvalPlugin` classes that hook into the `on_discover_adapters` lifecycle to register their custom execution protocols.
- **Ecosystem Hub**: A unified registry for LLM providers (**OpenAI**, **Gemini**, **Claude**, **Ollama**, **xAI Grok**) and orchestration frameworks. The Ecosystem Hub ensures the core evaluator remains "Zero-Touch"—swapping a provider requires zero core code changes. The LLM judge is now configurable via the `JUDGE_PROVIDER` environment variable, with support for per-scenario `judge_config` overrides.
- **Industry-Standard Rubrics**: The `rubrics.py` module provides a hot-swappable registry for clinical, fiduciary, and legal scoring logic, enabling precise evaluation without modifying engine code.
- **Judge Calibration**: The `calibrate` command analyzes `run.jsonl` flight logs to measure alignment between automated judges and human ground truth, calculating Pearson Correlation and Error metrics.

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint for `http` protocol |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `MAX_ENGINE_ATTEMPTS` | `50` | Evaluation security cap (attempts) |
| `JUDGE_PROVIDER` | `ollama` | Multi-model judge provider |
| `RUN_LOG_DIR` | `runs` | Directory for execution traces |
| `DEFAULT_ADAPTER_TIMEOUT` | `30` | Network timeout for agent adapters (seconds) |

## Test Suite

15+ test files covering core engine, metrics, drift ingestion, and triage. Run with:
```bash
python -m pytest
```

## Security Guardrails (Enterprise Audit)

The following mitigations are enforced at the core level:

| # | Threat | Mitigation | Location |
|---|---|---|---|
| 1 | DoS / CPU Exhaustion | `MAX_ENGINE_ATTEMPTS = 50` hard cap | `config.py` |
| 2 | PII / Token Leakage | `sanitize_payload()` redacts JWT, AWS, GitHub, Bearer tokens and neutralizes format-string injection | `events.py` |
| 3 | CLI Command Hijacking | `extend_cli` removed; plugins use namespaced `on_register_commands` under `multiagent-eval plugin <name>` | `cli.py`, `plugins.py` |
| 4 | Plugin Halt (Hang) | All hooks wrapped in `PLUGIN_TIMEOUT = 5.0s` via `_invoke_with_timeout()` | `config.py` |
| 5 | Sandbox Escape | Chroot on emitted state keys **and** values; shell meta-characters (`;`, `\|`, `&&`, `` ` ``) stripped | `config.py` |
| 6 | Fork Bomb | `MAX_FORK_DEPTH = 3`, `MAX_FORK_BREADTH = 5` enforced in `SessionManager` | `config.py` |
| 7 | RCE via Repro Scripts | Scripts output as inert `.txt`; `os.system`/`subprocess` strings stripped | `reporting_plugin.py` |
| 8 | Prototype Pollution | `EvaluationContext`/`TurnContext` are `frozen` dataclasses; nested dicts wrapped in `MappingProxyType`; history stored as `tuple` | `context.py` |
| 9 | Plugin GUI Hijacking | `AuthManager` Provider Pattern with secure, server-side session cookies (HttpOnly) | `auth_manager.py`, `app.py`, `App.jsx` |
| 10 | 401 Exfiltration | Centralized `apiFetch` with automatic 401 interception and Security Gateway redirection | `App.jsx` |

## Secure PBAC & Session Architecture

The Integrated Visual Suite uses a **Permission-Based Access Control (PBAC)** model to ensure Enterprise features are protected via granular security nodes:

1. **Auth Provider**: The backend utilizes an extensible `AuthManager` (Default: `StaticKeyProvider`).
2. **Granular Permission Nodes**: Security is enforced at the node level (e.g., `scenarios:read`, `eval:trigger`) rather than rigid roles, allowing for custom enterprise role mapping.
3. **Session Establishment**: The `/api/auth/login` endpoint initializes a secure, server-side Flask session upon valid credential verification.
4. **Cookie Governance**: Authentication is maintained via `HttpOnly` session cookies, mitigating CSRF and XSS-based token theft.
5. **Security Gateway**: The React frontend interceptors (via `apiFetch`) automatically trigger the 'Security Gateway' (Login Modal) upon 401 Unauthorized responses.
6. **Iframe Constraints**: Plugin iframes are constrained via `sandbox="allow-scripts allow-forms allow-popups"` to prevent top-level session hijacking.

## Visual Suite: React Flow Implementation

The Visual Suite has been fully migrated to **React Flow**, enabling:
- **High-Density Trajectories**: Fluid zoom and pan for 100+ node traces.
- **Glassmorphic UI**: Premium aesthetics with real-time tool overlays.
- **Auto-Centering**: Instant focus on tool-calls or identified root cause failure points.
- **Interactive State Inspection**: Deep dive into the VFS sandbox at any turn.

## High-Fidelity Triage Implementation

The `TriageEngine` uses a multi-layered forensic approach to identify the root cause of agent failures:

1.  **Level 1: Explicit Violations (100% Confidence)**: Direct policy breaches or evaluation plugin markers.
2.  **Level 2: Induced Errors (85% Confidence)**: Tracing back from system/tool exceptions to the preceding agent decision.
3.  **Level 3: Heuristic Divergence (50% Confidence)**: Identifying the last substantive decision before a run's failure signature.

Every identification includes a `reason` and `confidence` score, providing transparency into the automatic diagnostics process.
