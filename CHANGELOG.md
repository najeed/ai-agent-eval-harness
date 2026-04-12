# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-04-12

### Deep Forensics & Core Refinement
*   **Deep Forensics Engine (v1.5.0)**: Refactored the taxonomy engine from a monolithic heuristic scanner into a pluggable, registry-based diagnostic platform.
*   **Reduced Core Dependencies**: Eliminated the requirement for `sentence_transformers` and `numpy` dot-product logic in the Core harness.
*   **Centralized State Observability**: Migrated `state_read` and introduced `state_write` event emissions into the `SharedStateRegistry`, ensuring 100% forensic coverage for data lineage and industrial taint tracking.
*   **Granular Taint Tracking**: Enhanced the `SharedStateRegistry` to accept a centralized `event_bus` for unified infrastructure interaction monitoring.
*   **Causal Chain Attribution**: Implemented the `CausalChain` and `DiagnosticResult` models to distinguish between root-cause triggers (e.g., Logical Loop) and terminal symptoms (e.g., Infra Timeout).
*   **Enterprise Extension Support**: Re-categorized high-fidelity analyzers (Strategic Loops, Telemetry Gradients) as plugin-based examples, enabling users to inject advanced diagnostics via the `on_diagnose_failure` hook.
*   **Documentation & Test Sync**: Extensively updated both modern (Starlight) and legacy documentation to reflect the Core/Enterprise structural split.

## [1.4.2] - 2026-04-11

### AgentV Rebranding & Universal Architectural Purity
*   **Project Rebranding**: Formally renamed the framework to **AgentV** (`agentv` CLI). Synchronized all core logic, documentation, and metadata with the new identity.
*   **Universal Immutable Registry**: Implemented a boot-time indexed registry in `loader.py` using the `referencing` library. This ensures 100% deterministic, zero-I/O schema validation and anchors all forensic definitions for robust resolution.
*   **Windows URI Hardening**: Solved critical resolution bottlenecks by implementing canonical URI normalization, ensuring consistent behavior across heterogeneous environments.
*   **Forensic Transparency (Zero-Silence Pass)**: Executed a systematic refactoring of 12 core modules to eliminate all silent failure gates (`except Exception: pass`). Every deviation or systemic failure is now explicitly recorded in the forensic trail.
*   **Architectural Purity CI-Gate**: Introduced `tests/unit/test_architectural_purity.py` to permanently enforce the "Zero-Silence" standard and verify registry indexing integrity.
*   **Plugin Manager Hardening**: Fortified the `PluginManager` with strict registry schema validation and high-fidelity discovery logs.

## [1.4.1] - 2026-04-10

### Industrial Forensic Hardening
*   **Tier 3 Artifact Expansion**: Expanded the forensic whitelist to support all 20+ OOTB shims, including native support for `.sql`, `.patch`, `.sqlite3`, `.html`, and `.svg`.
*   **Identity Normalization**: Implemented automatic renaming of temporary trace files to `run.jsonl` during certification to eliminate "Run-ID Fragmentation."
*   **Namespace Affinity Enforcement**: Hardened the `ForensicRelevanceEngine` to strictly filter non-prefixed artifacts in shared directories, ensuring manifest optimization (<10KB).
*   **NIST-Aligned Scoring (WMS)**: Integrated the 7-dimension Weighted Severity Model (WSM) with a "Safety Floor" guardrail in `VerificationResult`.
*   **Administrative Gateway**: Added `AES_EXTRA_FORENSIC_EXTS` environment variable support for dynamic admin whitelisting.
*   **Forensic Ledger Normalization**: Implemented canonical extension aliasing (e.g., `.jpeg` -> `.jpg`, `.stdout` -> `.log`) to prevent audit chain gaps.
*   **Protocol Synchronization**: Explicitly documented the transition from legacy `KeyLoader` to the centralized `IdentityService`.
*   **Stabilized Verification**: Resolved architectural regressions in the forensic test suite, achieving a 100% pass rate.

## [1.4.0] - 2026-04-09

### Forensic Identity & VC v3 Standard
*   **Verification Certificate (VC) v3.0.0**: Introduced a new forensic manifest standard that mandates **Identity-based signing** and **Sidecar Artifact Hashing**.
*   **Forensic Evidence Ledger**: Implemented sidecar hashing (evidence ledger) to prevent "Side-Channel Tampering" of report artifacts (e.g., trajectory plots, HTML reports).
*   **AES v1.4 Specification**: Upgraded the core scenario standard to v1.4, enforcing mandatory metadata for `capabilities` and `standards_registry`.
*   **Centralized Identity Registry**: Introduced the `IdentityService` to manage public/private keys via `TRUST_ROOT`, enabling non-repudiable audit trails.
*   **Hardened Scenario Linter**: Upgraded `ScenarioLinter` with CLI support and support for v1.4 quality scoring.
*   **Massive Corpus Migration**: Batch-upgraded 5,000+ scenarios across 45+ industries to the AES v1.4 format.
*   **Scaffold v1.4**: Updated the `scaffold` command to generate v1.4 compliant directory structures and scenarios.

## [1.3.0] - 2026-04-06

### Industrial Registry & Forensic DNA
*   **Cumulative Registry Protocol**: Transitioned to a distributed, multi-layered configuration model (`shim_resources.d/`) to prevent "Extension Hobbling" and ensure core shim immutability.
*   **Schema-Driven Core Registry**: Implemented a "Hybrid" configuration registry (`shim_resources.json`) that decouples environmental state from functional logic.
*   **AES v1.3 Core Standard**: Upgraded the Agent Eval Specification to v1.3, promoting "Environmental DNA" (Provisioning Snapshots) to a first-class member of the evaluation trace.
*   **Forensic DNA Snapshotting**: `ToolSandbox` now automatically secures a SHA-256 `provisioning_hash` and a resolved property snapshot in every `run.jsonl`.
*   **Hybrid Configuration Protocol**: Native support for multi-source merging (JSON/YAML), git-ignored local secrets (`.local.json`), and cloud-native environment overrides (`AES_SHIM_RESOURCES_JSON`).
*   **Immutable Package Baseline**: Internalized sanctioned shim defaults at the package level for robust, zero-config Out-of-the-Box (OOTB) support.
*   **Async Execution Hardening**: Fully stabilized the `ToolSandbox.execute` async migration, resolving runtime regressions in the simulation layer.
*   **Additive Deep Merge**: Hardened the configuration engine to be strictly non-destructive (Add/Modify only), preserving core resources when extensions are layered.
*   **Security Diagnostics**: Enhanced `agentv doctor --registry` with absolute path masking to prevent sensitive directory leakage.

### Added
- **Registry Manager**: A hardened configuration loader in `eval_runner/config.py` with deep-merge capabilities and `jsonschema` validation.
- **Portability Layer**: Standardized `environmental_snapshot` in the `START` event of the AES trace for decoupled forensic auditing.
- **Shim Registry Integration**: Updated `ApiSimulator` and `GitSimulator` to consume declarative registry state at runtime.

### Security
- **Automated Secret Redaction**: Implemented a recursive redaction engine in the `RegistryManager` to mask sensitive credentials (`api_key`, `token`, `secret`) from being leaked in plain text into `run.jsonl` traces.

### Fixed
- **API Timeout Regressions**: Rectified `httpx` timeout parsing and dynamic header injection in `ApiSimulator`.
- **Scenario Version Compliance**: Updated `test_scenario_compliance.py` to support v1.3 while maintaining backward compatibility hooks for v1.2.
- **Test Baseline Synchronization**: Updated test files to reflect the AES v1.3 standard.

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
- **Security Audit (Doctor)**: Enhanced the `agentv doctor` utility with a dedicated security diagnostic phase to verify credential entropy, session governance, and PBAC node integrity.
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
- **CI/CD Gatekeeper**: Introduced the `agentv gate` command. This CLI tool enables "Hard Gating" in devops pipelines by enforcing cryptographic integrity (SHA-256/ED25519) and trace success before promotion.
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
- **`agentv init --standard <id>`**: New CLI flag to scaffold standard-specific evaluation environments.
- **`agentv aes add-standard`**: New CLI command to register custom industrial standards.
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
