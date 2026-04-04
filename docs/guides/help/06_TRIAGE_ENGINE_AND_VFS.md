# 🕵️ How AgentEval Isolates Root Causes (State-Level Triage)

AgentEval isolates the root cause of an agent's failure by moving beyond simple log analysis and into **State-Level Trajectory Triage**. It works across three distinct layers:

## 1. The "State Parity" Check (VFS Delta)
Unlike standard benchmarks that only check the agent's final text response, AgentEval maintains a **Virtual File System (VFS)**.

*   **VFS-Aware Shims**: Every World Shim (Database, Jira, Git, etc.) is "VFS-aware."
*   **State Comparison**: When an agent executes a tool, AgentEval compares the resulting system state against the "Ground Truth" defined in the scenario.
*   **Patient Zero**: If the agent queries the wrong table or fails to commit a file, the State Divergence is marked immediately as the "Patient Zero" step.

---

## 2. Heuristic Triage Engine (`triage.py`)
AgentEval uses a specialized engine to scan the entire execution trace for failure patterns:

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

By combining these, AgentEval can distinguish between an agent that hallucinated a tool's existence vs. an agent that used the right tool but with the wrong parameters.

---

## Why use Shims instead of Real APIs?

*   **Safety**: No risk of an agent accidentally deleting a production database or emailing a real customer.
*   **Determinism**: You can force the shim to "fail" (e.g., simulate a 500 Internal Server Error) to see how the agent handles errors.
*   **Speed**: Simulated responses are near-instant, vs. waiting for real network latency.
