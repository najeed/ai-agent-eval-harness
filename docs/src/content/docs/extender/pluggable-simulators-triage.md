---
title: Pluggable Simulators & Triage Classifiers
description: Customizing execution containment, action interception, and forensic triage.
---

AgentV provides clean, zero-touch hook interfaces to customize tool isolation boundaries, decorate simulator behaviors, and implement custom failure diagnostics.

---

## 🔌 1. Simulator Middleware

`SimulatorMiddleware` allows intercepting, mutating, or decorating actions executed on a simulator (e.g. introducing simulated latency, rate limiting, logging, or custom mocking).

### Interface Definition

To create a middleware, subclass `SimulatorMiddleware` and implement `process_action`:

```python
from eval_runner.simulators import SimulatorMiddleware, BaseSimulator
from typing import Any
from collections.abc import Callable, Coroutine

class LatencySimulationMiddleware(SimulatorMiddleware):
    async def process_action(
        self,
        simulator: "BaseSimulator",
        action: str,
        params: dict[str, Any],
        next_call: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
    ) -> dict[str, Any]:
        import asyncio
        # Pre-execution: Simulate network latency
        await asyncio.sleep(0.5)
        
        # Invoke the core handler or next middleware in chain
        result = await next_call()
        
        # Post-execution: Augment response metadata
        result["latency_simulated"] = True
        return result
```

### Registration

Middlewares can be registered dynamically on any simulator instance:

```python
sim = TerminalSimulator()
sim.register_middleware(LatencySimulationMiddleware())
```

---

## 🔒 2. Pluggable Jail Providers

All terminal execution simulators delegate physical command execution to a pluggable execution jail provider implementing the `BaseJailProvider` interface.

### The `BaseJailProvider` Interface

```python
from abc import ABC, abstractmethod
from typing import Any

class BaseJailProvider(ABC):
    @abstractmethod
    async def execute_command(
        self, cmd: str, cwd: str, env: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        """Execute a shell command within the isolated jail environment."""
        pass

    @abstractmethod
    async def cleanup(self, run_id: str) -> None:
        """Teardown and clean up execution sandbox resources (e.g. Docker containers)."""
        pass
```

### Swapping Jail Providers

By default, AgentV Core uses the lightweight `SubprocessJailProvider`. Enterprise extensions can swap this for containerized layers (e.g. Docker or gVisor):

```python
from eval_runner.simulators import TerminalSimulator

class DockerJailProvider(BaseJailProvider):
    async def execute_command(self, cmd, cwd, env, timeout):
        # Implementation executing cmd inside a dedicated Docker container...
        pass

    async def cleanup(self, run_id):
        # Teardown and remove the container for run_id
        pass

# Instantiate and configure
sim = TerminalSimulator()
sim.set_jail_provider(DockerJailProvider())
```

---

## ⏳ 3. Deterministic Quiescence

Simulators executing asynchronous background threads, caching database connections, or flushing file buffers can implement the `quiesce()` method to ensure the environment is fully settled before the Core performs assertions or state verification.

### Interface Definition

To implement quiescence, override the `quiesce` coroutine on your simulator:

```python
from eval_runner.simulators import BaseSimulator

class DynamicDatabaseSimulator(BaseSimulator):
    async def quiesce(self) -> None:
        # Flush connection pools and await outstanding disk commits
        await self.db_engine.dispose()
```

### Quiescence Timeout Guard
To prevent a slow or hanging custom simulator from blocking the main execution pipeline, the Core tool sandbox wraps all `quiesce()` invocations in a **5.0-second timeout guard** (`asyncio.wait_for`). If the simulator's quiesce phase hangs, the execution loop will log a warning and proceed without raising a blocking exception.

---

## 📦 4. Memory Partitioning (ShimResultProxy)

To satisfy zero-trust security boundaries, all simulator execution outcomes are wrapped inside a secure `ShimResultProxy` context.

### Encapsulation Rationale
The `ShimResultProxy` inherits directly from `dict` to ensure 100% backward compatibility with existing adapters, tests, and runner execution lines. However, it isolates raw metadata and cryptographic materials (like Ed25519 signing keys or raw telemetry DNA) away from standard dictionary keys.

### Usage Example
```python
from eval_runner.simulators import ShimResultProxy

raw_result = {"status": "success", "message": "Written", "keys": "secret_key_data"}
secure_metadata = {"signing_key": "ed25519_bytes"}

proxy = ShimResultProxy(raw_result, metadata=secure_metadata)

# 1. Guest agent only has access to standard keys
print(proxy["status"])  # "success"
print("keys" in proxy)  # False (metadata keys are stripped from the dict view)

# 2. Forensic verifiers retrieve metadata securely
print(proxy.get_secure_metadata())  # {"signing_key": "ed25519_bytes"}
```

---

## 🔬 5. Pluggable Triage Classifiers & Witnesses

The failure attribution layer supports custom classifiers and lazy witnesses to verify state invariants after execution completes.

### Unified Schemas

#### `TriageContext`
Wraps the evaluation run history and raw tool outcomes:
* `conversation_history`: List of messages (`list[dict[str, Any]]`)
* `task_result`: Evaluated execution result metadata (`dict[str, Any]`)

#### `TriageReport`
A structured diagnosis report:
* `category`: Standardized taxonomy failure code.
* `explanation`: Contextual forensic reasoning text.
* `index`: Zero-indexed turn number of failure occurrence.
* `confidence`: Attribution confidence score (`0.0` to `1.0`).
* `suggestion`: Recommended mitigation or fix action.

### Registering Classifiers

Register a custom classifier callable on the engine class:

```python
from eval_runner.triage import TriageEngine, TriageContext, TriageReport

def custom_llm_classifier(context: TriageContext) -> TriageReport | None:
    # Analyze the trajectory logs for failure indicators
    if "db_connection_refused" in context.task_result.get("error_msg", ""):
        return TriageReport(
            category="INFRA_CONNECTION_FAILED",
            explanation="Database failed to establish connection.",
            index=2,
            confidence=0.95,
            suggestion="Verify local database container lifecycle."
        )
    return None

# Register hook
TriageEngine.register_classifier(custom_llm_classifier)
```

### Lazy Witnesses (`BaseWitness`)

To run post-evaluation validation assertions on the environment state:

```python
from eval_runner.triage import BaseWitness, VerificationResult, TriageContext

class FilesystemWitness(BaseWitness):
    async def verify(self, context: TriageContext) -> VerificationResult:
        # Check physical invariants on disk
        import os
        if os.path.exists("/path/to/expected_output"):
            return VerificationResult(verified=True, explanation="Verification matches.")
        return VerificationResult(verified=False, explanation="Perjury detected: File missing.")
```

---

## 📈 6. Priority Forensic Analyzers

To override or intercept standard core failure diagnostics in the `FailureTaxonomy`, custom analyzers can be registered with a `priority` flag:

```python
from eval_runner.taxonomy import FailureTaxonomy, FailureCategory

def audit_trail_analyzer(task_result: dict) -> FailureCategory | None:
    if "untrusted_kms_cert" in task_result.get("auth_log", ""):
        return FailureCategory.POLICY_VIOLATION
    return None

# Register with priority flag set to True
FailureTaxonomy.register_analyzer(audit_trail_analyzer, priority=True)
```
