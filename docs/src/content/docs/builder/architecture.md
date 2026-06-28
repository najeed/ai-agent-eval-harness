---
title: System Architecture
description: Technical deep-dive into the AgentV engine, event bus, and security guardrails.
---

AgentV is built on a **"Zero-Touch Core"** philosophy. The central engine remains framework-agnostic, while all industry-specific logic, communication protocols, and simulators are injected via a pluggable architecture.

## 🏗️ High-Level Architecture

The system is divided into four distinct layers:

1.  **Entry Layer (CLI/API)**: Orchestrates the evaluation lifecycle and provides namespaced access to plugins.
2.  **Logic Layer (Engine & Session)**: Manages the turn-based conversation loop, state immutability via frozen contexts, and branching trajectories.
3.  **Simulation Layer (World Shims)**: Stateful, VFS-aware simulators that provide deterministic environment feedback.
4.  **Stability Layer (Process & PID)**: Singleton process enforcement and `psutil`-based stale loop remediation.
5.  **Security Layer (Identity & Trust)**: Cryptographic signature generation (VC v3) and NIST-aligned risk scoring.

---

## 🧩 CLI Architecture: Intent Lifecycle

The `agentv` CLI is structured around the industrial evaluation lifecycle. Every command is namespaced to prevent collision and ensure auditability.

### 1. Authoring & Scaffolding
- `init`: Scaffold new projects with industrial datasets.
- `scenario`: Generic scenario management (Generate/Inspect).
- `mutate`: Generate adversarial variants (ambiguity, injection).
- `analyze`: Proactive agent codebase scanning and AES scaffolding.

### 2. Discovery & Execution
- `list`: Filter and explore the local scenario registry.
- `run`: Execute single scenario or Benchmark URI.
- `evaluate`: Execute batch evaluation on a scenario dataset.
- `quickstart`: 120-second end-to-end evaluation demo.

### 3. Debugging & Diagnosis
- `replay`: Replay a previously recorded run trace.
- `explain`: Automated trace diagnostics for root cause analysis.
- `playground`: Interactive CLI REPL for agent testing.
- `record`: Real-time agent interaction logger.

### 4. Trust & Reporting
- `report`: Generate stylized premium HTML reports.
- `verify`: Cryptographic integrity check (Forensic Audit).
- `certify`: Generate signed Verification Certificates (VC).
- `gate`: CI/CD Hard Gate: Enforce verification/compliance.
- `aes`: AES Specification utilities (Validate/Register).

---

## 🧠 Evaluation Engine (Zero-Touch Core)

The core is a decoupled, event-driven architecture designed for enterprise hot-swapping:

1. **Runner (`runner.py`)**: Orchestrates the high-level loop and multi-attempt (`pass@k`) logic.
2. **SessionManager (`session.py`)**: Manages individual attempts, trajectories, and tool execution.
3. **AgentAdapterRegistry**: Dynamically discovers and registers agent protocols at runtime.
4. **ToolSandbox**: Managed execution environment with **Environmental DNA** snapshotting. Exposes pluggable `BaseJailProvider` sandboxing execution layers and a `SimulatorMiddleware` registry.
5. **Loader & Catalog**: Supports **Path Decoupling**, enabling scenarios to be loaded via Scenario ID or physical path.
6. **VerificationService (`verifier.py`)**: Central registry for trace signing and verification, supporting hybrid ML-DSA-65 / ED25519 signing with dynamic interceptor hot-swapping.
7. **ToolSandboxService (`tool_sandbox.py`)**: Context-isolated registry for intercepting, auditing, and filtering tool execution requests.
8. **MutationService (`mutator.py`)**: Orchestrates the chain of scenario mutator interceptors with concurrency safeguards for adversarial variant generation.
9. **OTel Telemetry Bridge (`otel_bridge.py`)**: standard observer plugin that maps core event signals (`CoreEvents.TOOL_CALL`, `CoreEvents.RUN_START`, `CoreEvents.ERROR`, etc.) to OpenTelemetry spans, enforcing context-bound parent/child trace context propagation.

---

## ⛓️ Interceptor & Pipeline Infrastructure

AgentV implements an extensible, zero-trust **Interceptor Pipeline Pattern** to allow secure runtime augmentation of cryptographic trace signing, tool sandboxing, and scenario mutation without modifying core engine logic.

### 1. Cryptographic Trace Signing Pipeline
*   **`TraceVerificationInterceptor`**: Abstract base class representing a trace verification plugin.
*   **`VerificationService` (`verification_service`)**: Thread-safe registry that routes signing and verification requests.
*   **Enterprise KMS/HSM Integration**: Supports dynamic hardware security module and key management service integrations where the private key bytes never touch the core environment.
*   **WORM Audit Trail Sealing**: Enables real-time writing of cryptographic proofs into an immutable, in-flight audit chain (`audit_chain.jsonl`) as part of the signing chain.

### 2. Tool Sandbox Interception Pipeline
*   **`ToolSandboxInterceptor`**: Abstract base class for tool execution auditing, mutation, and filtering.
*   **`ToolSandboxService` (`tool_sandbox_service`)**: Manages active tool execution interceptors.
*   **Asynchronous Context Isolation**: Powered by `contextvars.ContextVar` to enforce strict coroutine-level task isolation in concurrent asynchronous evaluation runs, eliminating configuration leakage across threads.
*   **Dynamic Capabilities**: Supports dynamic parameter injection, zero-trust boundary enforcement, and real-time transaction auditing.

### 3. Adversarial Scenario Mutation Pipeline
*   **`ScenarioMutator`**: Abstract base class for custom scenario generators and perturbation mutators.
*   **`MutationService` (`mutation_service`)**: Concurrency-guarded registry that chains mutators to inject adversarial perturbations (e.g., typos, instruction injection, cognitive ambiguity).
*   **Decoupled Extensibility**: Allows enterprise modules (like `IndustrialScenarioAugmentor`) to register custom mutation logic dynamically without modifying core perturbation routines.

---

## 🏗️ Technical Pillar: Process Orchestration

AgentV enforces a **Singleton Process Guard** to ensure that industrial evaluations remain deterministic and isolated.

### The Singleton Guard
- **PID-Based Locking**: The engine maintains a `.aes/lock/server.pid` file to prevent conflicting orchestration instances.
- **Stale Remediation**: Using `psutil`, the harness automatically detects and cleans up "ghost processes" from previous crashed runs, ensuring that the 5000-port and internal state remain clean.
- **Cross-Platform Parity**: The logic handles Windows file-locking quirks and Unix signals to provide a consistent `ATEPOST` cleanup lifecycle.

---

## 📡 The `EventEmitter` Bus

The heart of the system is the **Global Event Bus**. Every state transition in the engine is emitted as a structured event, allowing plugins to observe behavior without modifying core code. Subscribers can execute synchronously or asynchronously in dedicated background thread pools to minimize evaluation latency drag.

### Core Events
- `RUN_START` / `RUN_END`: Entire evaluation lifecycle.
- `TASK_START` / `TASK_END`: Individual goal execution.
- `PHASE` / `SUBTASK` / `ACTION`: **Behavioral DNA** markers for forensic analysis.
- `TOOL_CALL` / `TOOL_RESULT`: Interaction with World Shims.
- `HITL_PAUSE`: Request for human intervention.

### 🧬 OpenTelemetry Telemetry Bridge
The framework couples the event bus to OpenTelemetry tracing via the `OTelTelemetryBridge` observer.
- **Span Mapping**: Core events are automatically recorded onto the active OTel spans as structured span events (e.g., `tool.call` recording parameters).
- **Context Preservation**: Execution spans are bound to evaluation/turn context scopes (`otel_context`), avoiding global state leaks and facilitating W3C `traceparent` injection into outbound HTTP/SSE requests.

---

## 🛡️ Enterprise Security Guardrails

AgentV is designed for adversarial environments, enforcing strict guardrails at the core level:

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
