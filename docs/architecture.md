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
| Loader | `eval_runner/loader.py` | Universal dataset loading (CSV/JSONL), schema validation |
| Engine | `eval_runner/engine.py` | Multi-turn async loop with Lifecycle Hooks |
| Plugin Manager | `eval_runner/plugins.py`| Discovery and triggering of external capability hooks |
| Tool Sandbox | `eval_runner/tool_sandbox.py` | Stateful mock tool execution & governance policies |
| Metrics | `eval_runner/metrics.py` | Score calculation (tools, state, policy compliance, vibing) |
| Contexts | `eval_runner/context.py` | Typed `EvaluationContext` and `TurnContext` for stability |
| Reporter | `eval_runner/reporter.py` | Console report & Trajectory Mermaid generation |

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
