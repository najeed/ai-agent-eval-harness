---
title: State-Level Trajectory Triage
description: How AgentV isolates root causes using VFS Deltas and the Heuristic Triage Engine.
---

AgentV isolates the root cause of an agent's failure by moving beyond simple log analysis and into **State-Level Trajectory Triage**. It works across three distinct layers:

## 1. The "State Parity" Check (VFS Delta)

Unlike standard benchmarks that only check the agent's final text response, AgentV maintains a **Virtual File System (VFS)** logic within its simulators.

*   **VFS-Aware Shims**: Every World Shim (Database, Jira, Git, etc.) is "VFS-aware."
*   **State Comparison**: When an agent executes a tool, AgentV compares the resulting system state against the "Ground Truth" defined in the scenario.
*   **Patient Zero**: If the agent queries the wrong table or fails to commit a file, the State Divergence is marked immediately as the "Patient Zero" step.

---

## 2. Heuristic Triage Engine

The Triage Engine automatically scans the entire execution trace for failure patterns:

*   **Stall Detection**: Identifies if an agent is "looping" (e.g., calling the same `list_dir` 3 times without changing its behavior).
*   **Tool-Level Exceptions**: Captures internal simulator errors (e.g., a "404 Not Found" from the API Shim) that the agent might have ignored or misinterpreted.
*   **Policy Violations**: If a Security Shim blocks an action (like a regex-based data leak), the triage engine flags this as a critical failure point.

---

## 3. Visual Timeline Mapping

In the Visual Debugger, the **"Isolate Root Cause"** feature automatically scrolls the timeline to the exact node where the first Non-Success Signal occurred.

| Layer | What it detects | Why it matters |
| :--- | :--- | :--- |
| **State** | Data/File divergence | Catches "silent" failures where the agent *thinks* it succeeded. |
| **Logic** | Loops & Stalls | Identifies when an agent's reasoning has hit a dead-end. |
| **Security** | Policy Violations | Pinpoints exactly which guardrail was triggered and why. |

By combining these, AgentV can distinguish between an agent that hallucinated a tool's existence vs. an agent that used the right tool but with the wrong parameters.

---

## 4. Stratified Failure Taxonomy

To achieve industrial-grade diagnostics, AgentV has transitioned from brittle error string matching to a formal, **NIST-aligned Failure Registry**.

### Hierarchical Root-Cause Analysis
Failures are stratified into hierarchical categories:
1.  **INFRASTRUCTURE**: Simulator crashes, timeouts, or adapter connectivity issues.
2.  **LOGIC**: Reasoning loops, planning errors, or refusal to perform a task.
3.  **POLICY**: Violation of explicit tool-level or safety guardrails.
4.  **SECURITY**: Data leaks, PII exposure, or unauthorized access attempts.

### 🎯 Patient Zero Identification
The `TriageEngine` correlates these Enum-based failure codes with the **Behavioral DNA** telemetry. This allows the system to identify the **Patient Zero**—the exact step, turn, and tool-call responsible for the cascade. 

📖 See the full specification: [Failure Taxonomy](taxonomy.md)
