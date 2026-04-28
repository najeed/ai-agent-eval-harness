# AgentV Architecture: The Industrial Verification OS

AgentV is designed as a **Zero-Touch Core** system, ensuring the central evaluation engine remains framework-agnostic. All industry-specific logic, communication protocols (adapters), and World Shims (Environment Simulators) are implemented as modular plugins.

---

## 🚀 High-Level Data Flow: The Industrial Lifecycle

The harness orchestration flows through 8 logical intents, moving from design-time authoring to runtime execution and forensic verification.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   CLI (eval_runner/cli.py)                                  │
│  1. Authoring  2. Discovery  3. Execution  4. Debugging  5. Reporting  6. Trust  7. CI/CD   │
└──────────────┬──────────────────────────────┬──────────────────────────────┬────────────────┘
               │                              │                              │
               ▼                              ▼                              ▼
┌──────────────────────────────┐  ┌─────────────────────────────┐  ┌──────────────────────────┐
│   Authoring (mutate/spec)    │  │   Discovery (list/catalog)  │  │   CI/CD (ci/import)      │
│ • Mutator Engine             │  │ • Hybrid Registry           │  │ • Production Trace Bridge│
│ • AES Specification          │  │ • Optimized Catalog Service │  │ • Automated Scaling      │
└──────────────┬───────────────┘  └──────────────┬──────────────┘  └──────────────┬───────────┘
               │                                 │                                │
               └─────────────────────────────────┼────────────────────────────────┘
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                               Engine (eval_runner/session.py)                               │
│                                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                            DAG-Based Execution Loop (nodes/edges)                      │ │
│  │            [node_start] -> [turn_loop] -> [calculate_metrics] -> [node_end]            │ │
│  └────────────────────────────────────────────┬───────────────────────────────────────────┘ │
│                                               │                                             │
│  ┌──────────────────────────────┐             ▼              ┌────────────────────────────┐ │ 
│  │   Metrics (/metrics)         │◀─────────────────────────▶│   Tool Sandbox (sandbox.py)│ │ 
│  │ • Modular Category Evaluators│                            │ • Governance Policies      │ │ 
│  │ • High-Fidelity Judging      │                            │ • SharedStateRegistry      │ │ 
│  └──────────────────────────────┘                            └────────────────────────────┘ │
└───────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                                │ 
                                                ▼ 
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                Persistence & Forensic Reporting                             │
│                                                                                             │
│  • run.jsonl (Flight Recorder): Deterministic, streamable execution logs                    │
│  • triage.py: Heuristic failure tagging (CONNECTION_ERROR, POLICY_VIOLATION, etc.)          │
│  • Trace Verifier: Asymmetric signing and integrity verification (ED25519)                  │
│  • Integrated Visual Suite: React Flow dashboard for real-time trajectory analysis          │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧩 Module Inventory (Intent-Mapped)

| Intent | Key Modules | Purpose |
| :--- | :--- | :--- |
| **Authoring** | `analyzer.py`, `mutator.py` | Scaffold scenarios from code and generate adversarial variants. |
| **Discovery** | `catalog.py`, `config.py` | Unified Registry and high-performance scenario indexing. |
| **Execution** | `runner.py`, `session.py` | Orchestrates the eval loop with pass@k and multi-agent support. |
| **Debugging** | `explainer.py`, `triage.py` | Automated root cause isolation and step-by-step trace analysis. |
| **Reporting** | `reporting_plugin.py` | Generates Premium HTML reports and behavioral DNA heatmaps. |
| **Trust** | `verifier.py`, `auth_manager.py` | Cryptographic signatures (ED25519) and PBAC security nodes. |
| **CI/CD** | `drift_importer.py` | "Semantic Bridge": Convert production traces to evaluation rigor. |
| **Control** | `cli.py`, `console/` | Industrial control surface and Visual Debugger backend. |

---

## 🧠 Core Principles

### 1. Passive Observation (`EventEmitter`)
The core engine is built around a central `EventEmitter` (`eval_runner/events.py`). Every state transition—from a tool call to an agent response—is emitted as an event. This allows plugins to observe the system's behavior without modifying core logic.

### 2. Forensic DNA & Integrity
To satisfy high-stakes regulatory audits, every evaluation captures an immutable **Environmental DNA** snapshot:
- **Registry Snapshots**: The `ToolSandbox` captures the resolved state of all resources at the moment of initialization.
- **Asymmetric Trust**: Traces are signed with private keys and verified via public keys (VC v3 manifest), enabling non-repudiable audit trails.

### 3. Industrial Sandbox
The `ToolSandbox` provides a state-aware execution environment with automated workspace lifecycle management and granular governance policies.

---

## 🏭 Regulatory Alignment: NIST AI-100-1
AgentV is aligned with the **NIST AI RMF principles**, implementing:
- **Weighted Severity Model (WSM)**: Scoring across Safety, Security, Reliability, etc.
- **Safety Floor**: Automated capping of scores if critical dimensions fail.
- **Forensic Evidence Ledger**: Cryptographic binding of all sidecar artifacts.
