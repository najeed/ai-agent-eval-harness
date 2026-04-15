# AgentV Documentation: Legacy Resource Map

This document provides a transition bridge between the legacy `/docs-old` repository and the new persona-based documentation structure. It identifies which legacy files and specific sections map to each of the five core roles. The `/docs-old` directory remains supported as a reference for detailed technical narratives.

---

## 🧭 Persona Orientation

| Persona | Core Objective | Primary Interest |
| :--- | :--- | :--- |
| **Industry Evaluator** | Execution & Triage | Benchmarking, Dashboards, Drift Analytics |
| **Agent Integrator** | Integration | API Contracts, Tool Shims, Framework Adapters |
| **Platform Extender** | Extension | Plugins, Metrics, Custom Shims |
| **Security Auditor** | Trust & Verification | Cryptography, Non-repudiation, Hard Gating |
| **OSS Core Builder** | Scale & Performance | Architecture, Core Engine, Scaffolding, Registry Logic |

---

## 🗺️ Resource Mapping Table

| Legacy File | Primary Persona | Secondary / Partial Persona | Key Sections of Interest |
| :--- | :--- | :--- | :--- |
| [`cli_reference.md`](../docs-old/cli_reference.md) | **Evaluator** | Integrator, Builder | Full command suites for evaluation and scaffolding. |
| [`architecture.md`](../docs-old/architecture.md) | **Core Builder** | Extender | High-level data flow, Module inventory, Plugin lifecycle. |
| [`agent_api.md`](../docs-old/agent_api.md) | **Integrator** | Extender | Technical spec for agent-harness communication. |
| [`plugins.md`](../docs-old/plugins.md) | **Extender** | Core Builder | `BaseEvalPlugin` lifecycle and hook definitions. |
| [`SIGNING.md`](../docs-old/SIGNING.md) | **Auditor** | Evaluator | Key management, `gate` command CI/CD integration. |
| [`COMPLIANCE.md`](../COMPLIANCE.md) | **Auditor** | Core Builder | Forensic Governance, NIST AI-100-1 alignment. |
| [`trust_protocol_spec_v1.md`](../docs-old/spec/trust_protocol_spec_v1.md) | **Auditor** | Core Builder | Deep technical spec for VC v3 and Identity Service. |
| [`01_EVALUATION_GUIDE.md`](../docs-old/guides/01_EVALUATION_GUIDE.md) | **Evaluator** | Integrator | Baseline setup, running benchmarks, interpreting logs. |
| [`04_AES_SPECIFICATION.md`](../docs-old/guides/04_AES_SPECIFICATION.md) | **Builder** | Core Builder | Scenario JSON schema, Metadata requirements (v1.4). |
| [`05_DRIFT_AND_TRIAGE.md`](../docs-old/guides/05_DRIFT_AND_TRIAGE.md) | **Evaluator** | Core Builder | Triage heuristics and drift-import workflows. |
| [`07_SECURITY_AND_AUTHENTICATION.md`](../docs-old/guides/07_SECURITY_AND_AUTHENTICATION.md)| **Auditor** | Core Builder | PBAC architecture and session gating policies. |
| [`03_DEVELOPER_GUIDE.md`](../docs-old/guides/help/03_DEVELOPER_GUIDE.md) | **Core Builder** | Extender | Internal logic, state management, and dev environment. |
| [`07_WORLD_SHIMS_REFERENCE.md`](../docs-old/guides/help/07_WORLD_SHIMS_REFERENCE.md) | **Integrator** | Extender | Per-shim action lists and tool descriptions. |
| [`08_ADDING_WORLD_SHIMS.md`](../docs-old/guides/help/08_ADDING_WORLD_SHIMS.md) | **Extender** | Integrator | Best practices for developing new tool shims. |
| [`failure_taxonomy.md`](../docs-old/spec/failure_taxonomy.md) | **Evaluator** | Auditor | Hierarchical failure classification (NIST aligned). |

---

## 🛠️ One-to-Many Granular Mapping

For files that serve multiple personas through specific sections:

### 1. `architecture.md`
- **OSS Core Builder**: Full document (Module Inventory, Internal Data Flow).
- **Platform Extender**: Section 3 (Plugin Lifecycle) and Section 4 (World Shim Registry).
- **Security Auditor**: Section 5 (Forensic Trust Protocol).

### 2. `01_EVALUATION_GUIDE.md`
- **Industry Evaluator**: Full document (How to run, metrics interpretation).
- **Agent Integrator**: Section 2 (Environment Setup) and Section 4 (Quickstart).

### 3. `cli_reference.md`
- **Industry Evaluator**: Evaluation and Triage commands (`evaluate`, `run`, `drift`).
- **OSS Core Builder**: Management and System commands (`scaffold`, `doctor`, `init`).
- **Security Auditor**: Trust commands (`verify`, `gate`, `certify`).

### 4. `07_WORLD_SHIMS_REFERENCE.md`
- **Agent Integrator**: Essential tool usage descriptions.
- **Platform Extender**: Architectural patterns for shim state management.

## 🏁 Migration Status: 100% Complete

All legacy resources have been successfully migrated to the persona-based Starlight structure. The following mappings are now authoritative:

1.  **Evaluator**: `guide.md`, `drift.md`, `taxonomy.md`, `cli.md`, `advanced-publication-suite.md`.
2.  **Auditor**: `trust-protocol.md`, `security.md`, `compliance.md`, `verification.md`.
3.  **Integrator**: `quickstart.md`, `agent-contract.md`.
4.  **Extender**: `plugins.md`, `api-reference.md`, `shimming.md`, `triage-engine.md`.
5.  **Builder**: `architecture.md`, `developer-guide.md`, `core-functions.md`.

> [!NOTE]
> The `docs-old/` directory contains high-fidelity narrative guides and technical references. While modernized persona-based docs are preferred for onboarding, `docs-old` is maintained for forensic depth.
