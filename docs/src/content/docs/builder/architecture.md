---
title: System Architecture
description: Technical deep-dive into the MultiAgentEval engine, event bus, and security guardrails.
---

MultiAgentEval is built on a **"Zero-Touch Core"** philosophy. The central engine remains framework-agnostic, while all industry-specific logic, communication protocols, and simulators are injected via a pluggable architecture.

## 🏗️ High-Level Architecture

The system is divided into four distinct layers:

1.  **Entry Layer (CLI/API)**: Orchestrates the evaluation lifecycle and provides namespaced access to plugins.
2.  **Logic Layer (Engine & Session)**: Manages the turn-based conversation loop, state immutability via frozen contexts, and branching trajectories.
3.  **Simulation Layer (World Shims)**: Stateful, VFS-aware simulators that provide deterministic environment feedback.
4.  **Security Layer (Identity & Trust)**: Cryptographic signature generation (VC v3) and NIST-aligned risk scoring.

---

## 📡 The `EventEmitter` Bus

The heart of the system is the **Global Event Bus**. Every state transition in the engine is emitted as a structured event, allowing plugins to observe behavior without modifying core code.

### Core Events
- `RUN_START` / `RUN_END`: Entire evaluation lifecycle.
- `TASK_START` / `TASK_END`: Individual goal execution.
- `PHASE` / `SUBTASK` / `ACTION`: **Behavioral DNA** markers for forensic analysis.
- `TOOL_CALL` / `TOOL_RESULT`: Interaction with World Shims.
- `HITL_PAUSE`: Request for human intervention.

---

## 🛡️ Enterprise Security Guardrails

MultiAgentEval is designed for adversarial environments, enforcing strict guardrails at the core level:

| Threat | Mitigation |
| :--- | :--- |
| **Sandbox Escape** | Mandatory chroot on VFS keys and shell meta-character stripping. |
| **DoS / Infinite Loops** | `MAX_ENGINE_ATTEMPTS` (50) and `MAX_FORK_DEPTH` (3) caps. |
| **PII / Token Leakage** | `EventEmitter` automatically redacts JWTs, AWS keys, and Bearer tokens. |
| **Plugin Interference** | Contexts are `frozen` dataclasses using `MappingProxyType` for immutability. |
| **Hang Protection** | All plugin hooks are wrapped in a **5.0s timeout**. |

---

## 🧬 NIST AI-100-1 Alignment

The architecture is explicitly aligned with **NIST AI RMF principles**, providing a standardized baseline for mission-critical verification.

### Weighted Severity Model (WSM)
Aggregate scoring across 7 dimensions (Safety, Security, Reliability, etc.) ensures that risks are prioritized based on industrial impact.

### The "Safety Floor"
A architectural guarantee: If foundational **Safety** or **Security** scores fall below **0.5**, the aggregate trustworthiness index is automatically capped at **0.49 (Fail)**.

---

## 🔗 Identity & Trust (v1.4)

- **Identity Registry**: Central authority for managing Ed25519 signing keys.
- **Verification Certificate (VC) v3**: A signed manifest binding execution traces (`run.jsonl`) to environmental snapshots, ensuring absolute trace non-repudiation.
