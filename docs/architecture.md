# Architecture Overview

This document describes the system architecture of the AI Agent Evaluation Harness, following the "Visionary Core 2.0" evolution.

## High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             CLI (eval_runner/cli.py)                         │
│  • evaluate / import-drift / aes validate / replay                          │
└──────────────┬───────────────────┬────────────────────────┬─────────────────┘
               │                   │                        │
               ▼                   ▼                        ▼
┌───────────────────────────┐  ┌──────────────────────┐  ┌───────────────────────┐
│     Loader (loader.py)    │  │  AES Spec (/spec)    │  │  Drift (drift_imp...)  │
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
│  │ Metrics (metrics.py)      │◀──────────────▶│ Tool Sandbox (sandbox.py)│  │
│  │ • Pluggable Logic         │                │ • Governance Policies    │  │
│  │ • Path Efficiency         │                │ • SharedStateRegistry    │  │
│  └───────────────────────────┘                └──────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────────────────┘
                       │ 
                       ▼ 
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Persistence & Reporting                            │
│                                                                             │
│  • run.jsonl (Flight Recorder): Deterministic, streamable execution logs     │
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
| Engine | `eval_runner/engine.py` | Async evaluation loop with `run.jsonl` Flight Recorder emission |
| Plugin Manager | `eval_runner/plugins.py`| Lifecycle hooks for Enterprise and Research metrics |
| Tool Sandbox | `eval_runner/tool_sandbox.py`| Stateful mock executor with policy guardrails |
| Drift Importer| `eval_runner/drift_importer.py`| Conversion of production traces into regression scenarios |
| Triage Engine | `eval_runner/triage.py` | Automated failure categorization (Heuristic tagging) |
| AES Core | `/spec/aes/` | JSON Schema and Documentation for agent benchmarks |
| Metrics | `eval_runner/metrics.py` | Research-grade scoring: pass@k, Consensus, PII, and Refusal |
| Simulators | `eval_runner/simulators.py`| Deterministic tool shims (Git, API) for dependency-free testing |
| Mutator | `eval_runner/mutator.py` | Adversarial Mutation Engine for robustness red-teaming |
| Reporter | `eval_runner/reporter.py` | Consolidated console and HTML reporting with Triage integration |

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

## Simulation Lab & Research metrics

- **Simulation Shims**: State-aware mocks (Git Simulator) that enable testing complex agentic tasks (clone -> hack -> commit) without real infrastructure.
- **Research Metrics**: Native support for `pass@k` (robustness across attempts) and `Success Consistency`.
- **Adversarial Red-Teaming**: The `mutator` engine injects typos, prompt-injection, and ambiguity into scenarios to test agent edge-resistance.

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
