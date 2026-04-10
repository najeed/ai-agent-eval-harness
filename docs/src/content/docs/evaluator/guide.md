---
title: Evaluation Guide
description: Core philosophy behind MultiAgentEval scenarios and performance analysis.
---

This guide explains the philosophy behind our evaluation scenarios, the structure of the industrial corpus, and how to interpret results.

## 📚 The Industrial Corpus

MultiAgentEval ships with a production-grade corpus of **5,000+ scenarios** across 45+ industrial sectors. This includes:
- **Cross-Industry**: Inter-sector policy negotiation and data handoffs.
- **Ethical Guardrails**: Hardened safety, bias, and PII leakage tests.
- **Interactive Complexity**: Multi-turn flows involving Human-In-The-Loop (HITL).
- **Simulations**: High-fidelity lab environments (World Shims).

---

## 🏗️ Scenario Structure (AES)

Each evaluation is defined by an **Agent Evaluation Specification (AES)** file. Key components include:

- **`scenario_id`**: Unique identifier (e.g., `telecom-cs-001`).
- **`industry` & `use_case`**: Contextual categorization for [Industrial Benchmarking](/ai-agent-eval-harness/evaluator/industries/).
- **`initial_state`**: The starting sandbox state, supporting nested dot-notation.
- **`tasks`**: An ordered array of steps the agent must accomplish.

### Task Components
Each task within a scenario defines:
- **`expected_outcome`**: A high-level description of success.
- **`required_tools`**: The specific APIs the agent is expected to invoke.
- **`success_criteria`**: An array of metrics (e.g., `state_verification`, `tool_call_correctness`).

---

## ⚖️ Performance Metrics

| Metric | Category | Description |
| :--- | :--- | :--- |
| `tool_call_correctness` | Logic | Exact set-match of expected vs. actual tools. |
| `state_verification` | Practical | Verify persistent system state changes via dot-notation. |
| `policy_compliance` | Safety | Detect violations of explicit governance rules. |
| `delegation_loop_risk` | Efficiency| Detects infinite reasoning or re-planning cycles. |
| `luna_judge_score` | Semantic | Async LLM-based verification of answer quality. |

### Specialized Judge Rubrics
For semantic evaluations, you can specify rubrics like `clinical_safety`, `fiduciary_accuracy`, or `policy_adherence` within the `luna_judge_score` configuration.

---

## 🚀 Orchestration Modes

The harness supports three primary communication modes for agents:
1.  **HTTP**: Standard REST/JSON endpoint (Default).
2.  **Local**: Subprocess execution via `AGENT_LOCAL_CMD`.
3.  **Socket**: Direct TCP connection to a persistent agent server.

### Community Benchmarks
You can pull and format datasets from global benchmarks on-the-fly using URIs:
```bash
multiagent-eval evaluate --run-id <id>
multiagent-eval evaluate --run-id <id>
```

---

## 📊 Visual Analysis

Beyond the CLI, the **Visual Console** provides real-time playback of agent trajectories:
- **Trajectory Playback**: Step-by-step reconstruction of tool calls and state changes.
- **Forensic Triage**: Automatic identification of the "Patient Zero" step in a failure chain.
- **Mermaid Maps**: Visual DAG representation of the agent's reasoning path.

Launch with:
```bash
multiagent-eval console
```
