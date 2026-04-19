---
title: Singleton Process Guard
description: Technical deep-dive into AgentV's process orchestration and cross-platform stability.
---

# Industrial Stability

For high-stakes AI evaluation, engine stability is not optional. Conflicting instances, stale ports, or orphan processes can lead to non-deterministic results and diagnostic "ghosts." AgentV implements a **Singleton Process Guard** as a core architectural pillar.

## The Problem: Orphaned Orchestrators

In CI/CD environments or during local development, an evaluation process may terminate abruptly (e.g., due to a Ctrl+C, a timeout, or a system crash). If the underlying server (providing simulators or the console) remains running, subsequent runs will:
1.  **Fail to Bind**: Ports like `5000` or `1337` will be occupied.
2.  **Pollute State**: New evaluations might interact with state left behind by the previous process.
3.  **Consume Resources**: Memory and CPU leaks can degrade the reliability of the entire evaluation farm.

---

## The Solution: PID-Based Guarding

AgentV uses a multi-layered guard system powered by `psutil` to ensure that only one orchestration instance is active within a given `PROJECT_ROOT`.

### 1. The PID Lockfile
Upon startup, the engine attempts to create a lockfile at:
`.aes/lock/server.pid`

If the file exists, the harness doesn't just error; it enters the **Remediation Phase**.

### 2. Forensic Process Verification
Using `psutil`, the harness reads the PID from the lockfile and checks:
- **Existence**: Is a process with this PID still running?
- **Identity**: Does the process name match "python" and include "agentv" or "eval_runner" in its cmdline?
- **Ownership**: Was this process started from the current `PROJECT_ROOT`?

If the process is verified as a "stale ghost," the harness automatically terminates it (using `SIGTERM` followed by `SIGKILL` if necessary) to reclaim the resources.

### 3. Cleanup Lifecycle (`atexit`)
The harness registers a global cleanup handler using the `atexit` module. This ensures that:
- PID files are removed.
- Sub-processes (like the React development server or Ollama shims) are terminated.
- All world simulators are gracefully shut down.

---

## Cross-Platform Parity

Process management differs significantly between Windows and Unix-like systems. AgentV abstracts these differences:

| Feature | Unix/Linux | Windows |
| :--- | :--- | :--- |
| **Termination** | Uses `SIGTERM` / `SIGKILL`. | Uses `taskkill` logic via `psutil`. |
| **File Locking** | Standard `os.remove` logic. | Handles "File in Use" errors by retry loops. |
| **Cmdline Discovery** | Standard procfs. | Wraps WMI/Win32 APIs via `psutil`. |

## 🛠️ Developer Configuration

While the Stability Guard is proactive by default, you can tune it via environment variables:

- `AEH_DEBUG_PROCS=1`: Logs detailed process-tree snapshots during cleanup.
- `AEH_STRICT_SINGLETON=0`: Disables the guard (Not recommended for production/research).

> [!IMPORTANT]
> **Industrial Standard**: All AgentV contributors must ensure that any new long-running sub-processes are registered with the `SessionManager` to participate in this automated cleanup lifecycle.
