# Architecture Overview

This document describes the system architecture of the AI Agent Evaluation Harness.

## High-Level Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI (__main__.py)                        │
│  python -m eval_runner --industry telecom --scenario ...         │
└──────────────────────┬───────────────────────────────────────────┘
                       │ discovers .json files
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Loader (loader.py)                            │
│  • Loads scenario JSON from disk                                 │
│  • Validates against schemas/scenario.schema.json                │
│  • Loads CSV/JSONL datasets                                      │
└──────────────────────┬───────────────────────────────────────────┘
                       │ validated scenario dict
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Engine (engine.py)                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │            Multi-turn Conversation Loop                  │     │
│  │                                                          │     │
│  │  Turn 1: Send task_description → Agent API               │     │
│  │  Agent returns: {"action": "call_tool", "tool_name": X}  │     │
│  │                        │                                  │     │
│  │                        ▼                                  │     │
│  │              ToolSandbox (tool_sandbox.py)                │     │
│  │              • Persist/Mutate State (Milestone 1)         │     │
│  │              • Enforce Governance Policies (Milestone 2)  │     │
│  │              • Return status: "success" | "policy_violation"│     │
│  │                        │                                  │     │
│  │                        ▼                                  │     │
│  │  Turn 2: Send tool result or policy error → Agent API     │     │
│  │  Agent returns: {"action": "final_answer", ...}          │     │
│  │  → Loop ends                                             │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  Metrics (metrics.py)                                            │
│  • tool_call_correctness: set match of expected vs actual tools  │
│  • state_verification: verify system state changes (M1)          │
│  • policy_compliance: detect governance violations (M2)          │
└──────────────────────┬───────────────────────────────────────────┘
                       │ results list
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Reporter (reporter.py)                         │
│  • Prints per-task SUCCESS/FAILURE with metric scores            │
│  • Calculates overall success rate                               │
└──────────────────────────────────────────────────────────────────┘
```

## Module Inventory

| Module | File | Purpose |
|--------|------|---------|
| CLI | `eval-runner/__main__.py` | Argument parsing, scenario discovery, orchestration |
| Loader | `eval-runner/loader.py` | JSON loading, schema validation, CSV/JSONL datasets |
| Engine | `eval-runner/engine.py` | Multi-turn async conversation loop with agent API |
| Tool Sandbox | `eval-runner/tool_sandbox.py` | Stateful mock tool execution & governance policies |
| Metrics | `eval-runner/metrics.py` | Score calculation (tools, state, policy compliance) |
| Reporter | `eval-runner/reporter.py` | Console report generation |

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
