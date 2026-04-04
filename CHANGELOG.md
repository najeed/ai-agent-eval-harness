# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.4] - 2026-04-04

### Added
- **Native LangChain & LangGraph Support**: Implemented industrial-grade `ainvoke` support in both LangChain and LangGraph adapters with full `BaseCallbackHandler` integration.
- **High-Fidelity Telemetry Signals**: Introduced `CHAIN_START`, `CHAIN_END`, `NODE_START`, and `NODE_END` to the core event system for granular adapter tracing.
- **Cryptographic State Hashing**: Added SHA-256 state hashing and redacted metadata summaries to `on_chain_start` events for secure, audit-ready telemetry.
- **Protocol Versioning**: Enforced versioned URIs (e.g., `langgraph:v1`, `autogen:v1`) for immutable benchmarking and industrial-grade backward compatibility.
- **Adapter SDK Integration**: Migrated LangChain/LangGraph, AutoGen, and CrewAI from stubs to robust, SDK-aware implementations with dynamic import guards.
- **Standardized Adapter Verification**: Implemented a comprehensive test suite covering all versioned telemetry signals across the entire adapter stack.

## [1.2.3] - 2026-04-03

### Added
- **Operational Throttling**: Introduced `EVAL_TURN_THROTTLE` to prevent resource exhaustion and satisfy rate-limiting requirements in sensitive sectors.
- **Robust Regression Test Suite**: Implemented new unit and integration tests covering plugin discovery, PBAC security, console hydration, and trace robustness.
- **Recursive Trace Aggregation**: Added `rglob` support to `calibrator.py` for recursive directory scanning in deep trace hierarchies.
- **Industrial Permission-Based Access Control (PBAC)**: Replaced rigid RBAC with a granular, string-based permission node system (`scenarios:read`, `eval:trigger`, etc.).
- **Enterprise Auth Provider Pattern**: Refactored `AuthManager` abstraction to support extensible PBAC mapping for OIDC, SAML, and custom identity providers.
- **Security Audit (Doctor)**: Enhanced the `multiagent-eval doctor` utility with a dedicated security diagnostic phase to verify credential entropy, session governance, and PBAC node integrity.
- **Session-Based Authentication**: Transitioned from plaintext storage to secure, server-side Flask sessions using `HttpOnly` and `SameSite` cookies.
- **Hardened Trust Protocol**: Fully realized the Open Core Verification Engine, ensuring 100% trace integrity.
- **HMS-Ready Architecture**: Multi-tier `KeyLoader` refactor allowing the Trust Protocol to scale to KMS/HSM production environments.
- **Public Certificates API**: Implemented the REST endpoint `/api/v1/certificates/<run_id>` for non-repudiable, non-authenticated audit access.

### Security
- **SSRF/Metadata Protection**: Implemented IP-level validation in `RemoteBridgePlugin` to block access to loopback (`127.0.0.1`) and cloud metadata (`169.254.169.254`) endpoints.
- **Telemetry Masking**: Added a recursive telemetry scrubbing layer in `TraceRecorder` to mask secrets and PII from execution logs (Audit Point #2).
- **Path Traversal Hardening**: Enforced strict `Path.resolve()` jail-checks across all dashboard routes to prevent unauthorized directory access.
- **Auth Enforcement**: Promoted `X-AES-API-KEY` to a mandatory header for all management console routes when `DASHBOARD_API_KEY` is configured.

### Fixed
- **Plugin Discovery Bug**: Resolved a critical issue in `eval_runner/plugins.py` where internal essential plugins were identified but not getting instantiated.
- **BOM-Safe Trace Loading**: Hardened `trace_utils.py` with `utf-8-sig` support to handle Byte Order Marks and malformed JSONL gracefully.
- **CLI Circular Dependencies**: Implemented PEP 562 lazy-loading for command handlers to decouple CLI entry points from heavy internal dependencies.
- **AsyncIO Loop Drift**: Stabilized `doctor.py` connectivity checks by ensuring strict event loop synchronization.
- **Frontend Security Reconciliation**: Implemented a centralized, PBAC-aware `apiFetch` utility and global auth-state management in Visual Debugger.
- **401/403 Unauthorized Interception**: Added automated frontend routing to the 'Security Gateway' (Login Modal) upon permission node rejection.

### Changed
- **Internal Plugin Manifest**: Promoted `FlightRecorderPlugin` and `ReportingPlugin` to the immutable internal discovery manifest.
- **Scenario Schema Hardening**: Enforced mandatory `name`, `nodes`, `edges`, and `consensus.strategy` fields in `scenario.schema.json`.
- **Granular Least-Privilege**: All console API routes now enforce specific permission nodes rather than broad role-based access.
- **Secure-by-Design**: `DASHBOARD_API_KEY` is now mandatory for all sensitive console operations, with automated entropy validation.

## [1.2.2] - 2026-03-31

### The Trust Protocol Release
- **Asymmetric Trust Protocol**: Implemented ED25519 signing and verification in the Open Core `TraceVerifier`. Ensures non-repudiable audit trails for all agentic evaluations.
- **CI/CD Gatekeeper**: Introduced the `multiagent-eval gate` command. This CLI tool enables "Hard Gating" in devops pipelines by enforcing cryptographic integrity (SHA-256/ED25519) and trace success before promotion.
- **Fintech Scenario Pack**: Expanded the global industrial corpus with the Fintech Pack (Series 11198–11207 + Recovery 11252), achieving a 100/100 GOLD linter score across all new scenarios.
- **Behavioral Fingerprinting V1**: Formalized the Fingerprint schema for standardizing base-level behavioral snapshots in evaluation traces.

## [1.2.1] - 2026-03-30

### Stabilization & Hardening
- **Zero-Touch Core**: Transitioned to dynamic plugin and adapter discovery, removing manual registration overhead.
- **Data Externalization**: Decoupled mock data from core providers; industry-specific collections are now managed via the `/industries` directory.
- **Path Hardening**: Eliminated all absolute path dependencies in favor of project-local, environment-agnostic relative paths.
- **Distribution Manifest**: Refined `pyproject.toml` to ensure full coverage of engine assets and industry data providers in package builds.
- **Documentation Audit**: Reconciled and hardened all architectural and specification guides for full AES v1.2 compliance.

### AES v1.2 Implementation
- Implement dynamic state-aware simulators (Jira, Git, Cloud).
- Enforce strict AES v1.2 schema validation (DAG-based workflows).
- Refactor simulator registry for 100% test isolation (Factory pattern).
- Migrate entire test suite to unified v1.2 specification.
- Finalize fail-fast engine logic for acyclic DAG execution.

## [1.2.0] - 2026-03-28

### Added
- **DAG Workflow Engine**: Formal support for Directed Acyclic Graph (DAG) structures in scenarios, replacing the legacy linear `tasks` arrays.
- **Industrial Standards Registry**: Integration of industrial standards (e.g., ISO 20022, HL7 FHIR) into the core evaluation loop and scaffolding.
- **`multiagent-eval init --standard <id>`**: New CLI flag to scaffold standard-specific evaluation environments.
- **`multiagent-eval aes add-standard`**: New CLI command to register custom industrial standards.
- **Spec-to-Eval Utility**: LLM-aided tool to transform natural language PRDs into compliant AES scenario files.
- **Atomic Shift**: Batch migration of 5,000+ industry scenarios to the new DAG format.

### Changed
- **Unified Standard**: Removed `aes_version` guards and legacy `tasks` references in favor of a single, hardened workflow specification.
- **`SessionManager`**: Enhanced with a robust dependency resolver for node-based task execution.
- **`ScenarioLinter`**: Updated to validate DAG integrity and industrial standard compliance.
- **`mutator.py` & `enrich_scenarios.py`**: Refactored to support the new `workflow.nodes` architecture.

### Fixed
- Sanitized 44+ industry documentation files to ensure UTF-8 compliance and remove non-standard characters.
- Synchronized `scenario.schema.json` with the core AES specification.
