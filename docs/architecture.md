# Architecture Overview

This document describes the system architecture of the AI Agent Evaluation Harness.

## High-Level Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI (cli.py)                            │
│  python -m eval_runner evaluate --industry telecom               │
└──────────────────────┬─────────────┬─────────────────────────────┘
                       │             │
                       ▼             ▼
┌───────────────────────────┐  ┌───────────────────────────┐
│     Loader (loader.py)    │  │ PluginManager (plugins.py)│
│ • LoaderRegistry (CSV/..) │  │ • Lifecycle Hooks         │
│ • Schema Validation       │  │ • External Extensions     │
└──────────────┬────────────┘  └─────────────┬─────────────┘
               │ validated scenario          │
               ▼                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Engine (engine.py)                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │     Multi-turn Conversation Loop (with hooks)           │     │
│  │                                                          │     │
│  │  [before_evaluation] -> [on_turn_end] -> [after_eval]    │     │
│  │                                                          │     │
│  │  EvaluationContext  &  TurnContext (typed)               │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  Registries (metrics.py, loader.py, engine.py)                   │
│  • MetricRegistry: Pluggable calculation functions               │
│  • LoaderRegistry: Pluggable dataset parsers                     │
│  • AgentAdapterRegistry: Pluggable communication protocols       │
└──────────────────────┬───────────────────────────────────────────┘
                       │ results list
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Reporter (reporter.py)                         │
│  • Console reports & Markdown for PR Comments                    │
│  • Trajectory Mermaid Visualization                             │
└──────────────────────────────────────────────────────────────────┘
```

## Module Inventory

| Module | File | Purpose |
|--------|------|---------|
| CLI | `eval_runner/cli.py` | Argument parsing, scenario discovery, orchestration, plugin extensions |
| Loader | `eval_runner/loader.py` | Universal dataset loading (CSV/JSONL), schema validation (v2.0) |
| Engine | `eval_runner/engine.py` | Multi-turn async loop with Lifecycle Hooks |
| Plugin Manager | `eval_runner/plugins.py`| Discovery and triggering of external capability hooks |
| Tool Sandbox | `eval_runner/tool_sandbox.py`| Stateful mock tool execution & `SharedStateRegistry` |
| Metrics | `eval_runner/metrics.py` | Score calculation (tools, state, multi-agent consensus, loop-risk) |
| Contexts | `eval_runner/context.py` | Typed `EvaluationContext` and `TurnContext` for stability |
| Reporter | `eval_runner/reporter.py` | Console report & Trajectory Mermaid generation |

## Multi-Agent Orchestration

Phase 1 of Core 2.0 introduces support for agent "crews":
- **`SharedStateRegistry`**: A namespaced synchronization protocol within the sandbox that allows agents to share state (e.g., `billing:dispute`) based on configured read/write permissions.
- **`agent_topology`**: Defined in the scenario schema to control visibility and access between agents.
- **Delegation Metrics**: `delegation_latency` tracks handoff efficiency, while `delegation_loop_risk` detects infinite re-planning cycles.
- **Consensus Judge**: A semantic similarity evaluator (LLM-lite) for scoring agreement between agents.

## Semantic Bridge & Drift Management

Phase 2 focuses on bridging high-level requirements with evaluation data:
- **`spec_parser.py`**: A robust Markdown-to-Scenario parser supporting structured PRDs. It extracts metadata, sequential tasks, policies, and topology into v2 JSON.
- **Grounding Coverage Heatmap**: A visual reporting layer (`coverage_reporter.py`) that tracks which domain policies and KB tools were exercised during an evaluation, generated via the `CoveragePlugin`.
- **`spec-to-eval` CLI**: Automates the conversion from Markdown specifications to executable scenarios.

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |

## Data Assets

- **44 industries** with **4,400+ scenarios** in `/industries`
- **Schema** at `schemas/scenario.schema.json` (Draft-07)
- **Sample agent** at `sample_agent/agent_app.py` (Flask, rule-based, telecom only)

## Test Suite

8 test files, 50+ tests. Run with:
```bash
pytest tests/ -v
```
