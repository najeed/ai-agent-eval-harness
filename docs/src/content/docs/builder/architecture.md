---
title: System Architecture
description: Deep dive into the MultiAgentEval Zero-Touch Core and modular plugin architecture.
---

MultiAgentEval is built on a **Zero-Touch Core** philosophy: the central engine remains immutable and framework-agnostic, while all domain-specific logic, protocols, and environments are injected via modular plugins.

---

## 🏗️ High-Level Map

The harness is divided into four authoritative layers:

1. **The CLI Layer** (`eval_runner/cli.py`): Command dispatching, argument parsing, and environment initialization.
2. **The Loader Layer** (`eval_runner/loader.py`): Universal scenario loading, industry dataset extraction, and hybrid registry resolution.
3. **The Execution Layer** (`eval_runner/session.py` / `engine.py`): The heart of the platform. Manages turn loops, immutable contexts, and state transitions.
4. **The Observation Layer** (`eval_runner/events.py`): A decoupled `EventEmitter` bus that triggers metrics, reporting, and triage plugins.

---

## 🔐 The "Zero-Touch" Hardening (v1.3.0)

For the **OSS Core Builder**, the most significant architectural advancements in v1.3.0 focus on stability and isolation:

### 1. Isolated Contextual Registries
We have moved away from a shared global registry for agent adapters, tools, and simulators. The platform now uses a **Local Overlay Pattern**:
- **Mechanism**: `contextvars`-based isolation ensures that a mock or override in one evaluation task cannot leak into concurrent runs.
- **SSOT**: The global registry remains the authoritative discovery cache, but the `SessionManager` executes within a virtualized "Overlay Context."

### 2. Forensic DNA & Snapshots
Every evaluation now captures an immutable **Environmental DNA** snapshot:
- **Provisioning Hash**: A SHA-256 hash of the *resolved* registry state (endpoints, shims, versions) is recorded in the trace.
- **Mathematical Proof**: This hash is cryptographically linked to the **Trust Protocol** signing step, proving the environment was not tampered with during execution.

---

## 📡 The Event Bus (`EventEmitter`)

The core is non-intrusive. Every major action emits an event, allowing builders to extend functionality without modifying the engine.

| Event Type | Purpose |
| :--- | :--- |
| `PHASE` | Hierarchical macro-segments of a mission. |
| `NODE_START` | Entry into a specific DAG workflow node. |
| `ACTION` | High-level agent decisions or tool executions. |
| `DNA_SIGNAL` | Telemetry from underlying frameworks (e.g., LangGraph). |

---

## 📦 Core Module Inventory

| Module | Purpose | Source |
| :--- | :--- | :--- |
| **Session** | Manages immutable turn-contexts and conversation state. | `eval_runner/session.py` |
| **Tool Sandbox** | Stateful mock executor with policy guardrails. | `eval_runner/tool_sandbox.py` |
| **Metrics** | Modular evaluators for Accuracy, Planning, and Defense. | `eval_runner/metrics/` |
| **Simulators** | World Shim suite (20+ simulators) for high-fidelity testing. | `eval_runner/simulators.py` |
| **Triage** | Forensic trajectory forensics and root cause isolation. | `eval_runner/triage.py` |

---

## 🛡️ Security Guardrails

The engine enforces industrial-grade mitigations at the binary level:
- **CPU Exhaustion**: Hard cap of `50` engine attempts per scenario.
- **PII Redaction**: Centralized payload sanitization for JWTs, AWS keys, and GitHub tokens.
- **Sandbox Escape**: Chroot-based virtualization of all emitted state keys and terminal paths.
- **Prototype Pollution**: `EvaluationContext` and `TurnContext` are **frozen dataclasses**.

---

## 🧭 Integration Guide
- **Developing Plugins**: See the [Plugin Extension Guide](../../extender/plugins/).
- **Adding Simulators**: Learn how to build new [World Shims](../../extender/simulators/).
