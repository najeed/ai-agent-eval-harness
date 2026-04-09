---
title: Triage Engine & VFS
description: Deep dive into the forensic state-level triage and Virtual File System (VFS).
---

MultiAgentEval isolates the root cause of an agent's failure by moving beyond simple log analysis and into **State-Level Trajectory Triage**.

## 1. The "State Parity" Check (VFS Delta)

Unlike standard benchmarks that only check for text output, MultiAgentEval maintains a **Virtual File System (VFS)**.
- **VFS-Aware Shims**: Every [World Shim](/ai-agent-eval-harness/extender/shimming/) (Database, Git, Slack, etc.) is "VFS-aware."
- **State Comparison**: When an agent executes a tool, the engine compares the resulting sandbox state against the ground truth defined in the scenario.
- **Patient Zero**: If the agent queries the wrong table or fails to commit a file, the State Divergence is flagged immediately as the "Patient Zero" step.

---

## 2. Heuristic Triage Engine

The triage engine scans the execution trace for complex failure patterns:
- **Stall Detection**: Identifies if an agent is "looping" (e.g., calling the same `list_dir` 3 times without changing behavior).
- **Tool-Level Exceptions**: Captures internal simulator errors (e.g., a "404 Not Found" from an API Shim) that the agent might have suppressed.
- **Policy Violations**: Pinpoints exactly which guardrail was triggered in the [Security Protocol](/ai-agent-eval-harness/auditor/security/).

---

## 3. Visual Root Cause Isolation

In the [Visual Console](/ai-agent-eval-harness/evaluator/user-manual/), the **"Isolate Root Cause"** feature automatically scrolls the trajectory timeline to the exact node where the first non-success signal occurred.

| Layer | What it detects | Why it matters |
| :--- | :--- | :--- |
| **State** | Data/File divergence | Catches "silent" failures where the agent *thinks* it succeeded. |
| **Logic** | Loops & Stalls | Identifies when an agent's reasoning has hit a dead-end. |
| **Security** | Policy Violations | Pinpoints exactly which guardrail was triggered and why. |

---

## 4. Stratified Failure Taxonomy

Diagnostics are aligned with the formal [Failure Taxonomy](/ai-agent-eval-harness/evaluator/taxonomy/), categories into:
1.  **INFRASTRUCTURE**: Simulator crashes, timeouts, or connectivity issues.
2.  **LOGIC**: Reasoning loops, planning errors, or task refusals.
3.  **POLICY**: Violation of tool-level governance rules.
4.  **SECURITY**: Data leaks and unauthorized access attempts.

By correlating these failure codes with **Behavioral DNA** telemetry (`CHAIN_START`, `NODE_START`), the system provides transparency into even the most complex multi-agent reasoning paths.
