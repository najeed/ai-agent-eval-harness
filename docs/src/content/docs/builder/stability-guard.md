---
title: Singleton Process Guard
description: Technical deep-dive into AgentV's process orchestration and cross-platform stability.
---

`eval_runner.console.app.manage_pid_file()` runs when the Console server starts.
It uses `.aes/server.pid` to find a previous Console process and records the new
PID. It skips the Werkzeug reloader child to avoid terminating its parent.

## Current checks

For a different live PID, the guard checks whether its process name contains
`python`, sends termination, waits up to five seconds and then kills it if needed.
It does not verify the previous process's command line, working directory or
project ownership. Do not treat the PID file as a cross-user authorization lock.

The exit handler deletes the PID file only if it still contains this process's
PID. It does not provide a general registry for terminating React servers,
Ollama processes or all world shims. Evaluation sandbox teardown and provider
certification transactions have their own lifecycles.

This guard applies to Console startup, not every evaluation invocation. There is
no `AEH_STRICT_SINGLETON` or `AEH_DEBUG_PROCS` control, nor a 24-hour stale-lock
recycling policy. Deployment process supervision and run-provider transactional
locking must handle concurrency beyond this local development guard.
