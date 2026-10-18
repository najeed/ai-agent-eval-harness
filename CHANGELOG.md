# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-12

### Added
* **Standalone Extension Lifecycle CLI & Fast-Path Dynamic Discovery**: Promoted `agentv extension` (`publish`, `activate`, `rollback`, `unpublish`, `verify`, `repair`) to a first-class, standalone CLI command with dedicated `_dispatch_extension` dispatcher, executing <50ms offline cryptographic and artifact checks. Decoupled extension lifecycle management completely from web server startup and route blueprints by migrating `_public_key_pem_bytes` and `_private_key_pem_bytes` into `extension_publisher.py` (re-exported in `routes/trust.py` for full compatibility). Removed `console` from `DISCOVERY_COMMANDS` to avoid eager agent adapter registry discovery during console operations, while retaining `agentv console extension ...` as a seamless backward-compatible alias.
* **Fail-Closed Airgap Boundary Enforcement & Anti-DNS Rebinding**: Implemented `AIRGAPPED_MODE=true` fail-closed configuration and `AirgappedConfigurationError`. Added `assert_airgap_safe_endpoint()` and `is_airgap_safe_host()` performing destination-IP resolution and private IP range validation (RFC 1918, loopback, link-local, private IPv6) across all HTTP adapters and LLM providers (`OpenAIProvider`, `AnthropicProvider`, `GeminiProvider`, `GrokProvider`, `OllamaProvider`). Added anti-DNS rebinding defenses via destination-IP pinning, HTTP redirect hop trace inspection under airgap mode, and configurable Visual Console CSP (`CONSOLE_CSP`) with dynamic CDN stripping (`https://cdn.jsdelivr.net`) and local offline Mermaid diagram bundling (`get_mermaid_asset_url()`).
* **WORM Storage Tier Governance & Fail-Closed Certification Gate**: Formally classified `LocalFileArtifactStore` as `TAMPER_EVIDENT_LOGICAL_SEAL`. Introduced `REQUIRE_IMMUTABLE_WORM=true` certification gate enforcing fail-closed rejection of logical seals when physical hardware WORM storage is required by compliance policy. Implemented zero-touch WORM retention metadata propagation (`retention_days`, `retention_until`, `legal_hold`) in `.meta.json` sidecars, sealed manifests, and `on_artifact_created` plugin hook dispatch.
* **Durable Human-in-the-Loop (HITL) Lifecycle & Monotonic Resumption**: Implemented dedicated `RunSuspendedForApproval` exception and `PAUSED_FOR_APPROVAL` state in `RunLifecycleState`. Built durable `ApprovalStore` and `ApprovalRequest` contracts with `FileApprovalStore` and `SQLiteApprovalStore` reference backends. Supported same-run resume preserving existing execution vaults and `execution_manifest.json` without run ID collision, with monotonic sequence continuation (`is_resume=True`, `_seq = max(_seq) + 1`) in `FlightRecorder`. Added CLI command `agentv hitl-resume` (`--run-id`, `--approval-token`, `--decision`, `--reviewer`, `--reason`, `--store`), emitted `APPROVAL_CREATED` and `APPROVAL_RESOLVED` events, dispatched `on_approval_created` and `on_approval_resolved` plugin hooks, and preserved scenario contract snapshots (`scenario_resolved.json`).
* **Unified 9-Vector Adversarial Mutation Ecosystem ($V \times O \times T$) & Static Linter Chaining**: Expanded mutation taxonomy to a 9-vector coordinate matrix across Input, Context, Memory, Retrieval, Tool, State, Authorization, Temporal, and Objective spaces (35+ registered catalog mutators). Integrated `ScenarioLinter` in-memory static analysis (`lint_dict()`) into `ScenarioMutator`, `agentv mutate`, and Visual Console `POST /v1/mutate` with tiered compliance scoring (`GOLD` 100/100, `SILVER` 80-99, `BRONZE`, `REJECTED`). Added tenant isolation via `org_id` on `GET /api/v1/mutations`.
* **High-Performance Zero-Touch CLI Dispatch Architecture**: Implemented lazy subparser compilation and isolated dynamic entry-point discovery via `STATIC_PROTOCOLS`, `DISCOVERY_COMMANDS`, and `_should_load_cli_extensions()`, enabling sub-100ms startup times for lightweight commands (`--help`, `--version`, `aes validate`, `lint`, `inspect`). Added `agentv hitl-resume`, `agentv lint`, and authoritative `--execution-mode [live|hybrid|simulated]` on `agentv run`.
* **External Tool Receipts Ingestion & Provenance Boundary**: Ingested agent self-reported external tool execution trajectories via typed `EXTERNAL_TOOL_CALL` and `EXTERNAL_TOOL_RESULT` events labeled with `source="external_agent_telemetry"` and `provenance="reported"`. Established strict provenance boundaries where external tool executions are counted under `external_tool_calls_observed` in `CertificationService` and strictly prohibited from masquerading as AgentV-sandbox-authoritative.
* **External State Authorities & Bounded State Contract**: Implemented `ExternalStateAuthority` interface and registry for independent pre/post-action state observation. Defined `BoundedStateProvider` contract (`query_bounded_reference`, `commit_state_transition`), strictly throwing `EvidenceBoundednessViolationError` on `get_all_state()` calls to prevent memory exhaustion and unredacted data dumps.
* **Declarative AST Regulatory Policy Engine**: Refactored policy evaluation into a pure declarative AST condition-constraint engine (`evaluate_declarative_rule` in `eval_runner/reference/field_policy.py`), supporting `when` triggers, multi-reason failure aggregation, and execution modes (`deterministic`, `semantic`, `hybrid`) with pre-compiled regulatory policies (WA ESSB 5395 and IA HF 2635).
* **Immutable Run Hard-Freeze Lifecycle & TOCTOU Prevention**: Implemented authoritative three-state lifecycle machine (`RUNNING` → `FINALIZING` → `SEALED`) in `FlightRecorder`, rejecting post-freeze telemetry writes (`handle_event`) and eliminating size-based file truncation rollbacks in favor of immutable artifact sealing.
* **Deterministic Evidence Root Derivation & Causal Contract Binding**: Verification pipeline dynamically derives `evidence_root_hash` from trace event assertion sets via `build_evidence_graph_from_events` and `compute_evidence_graph_root`, enforcing fail-closed `EvidenceRootMismatch` validation and binding evaluation contract parameters (`scenario_id`, `scenario_hash`, `policy_id`, `evaluator_config_hash`, `agent_id`, `agent_identity`) into signed manifests.
* **Public-Key Only Cryptographic Verification**: Refactored `verify_trace_certificate()` to operate exclusively on public keys (`IdentityService.get_public_key()` or embedded public keys), eliminating private key access during verification; enforced `require_signature=True` default across `VerificationAuthority.verify_package()`.
* **Authoritative Console Verification & Public Route Hardening**: Upgraded console `_authoritative_verdict` to execute full `TraceVerifier.verify_trace()` cryptographic validation, disentangled compliance scores from cryptographic validity in public verification endpoints, isolated RCA temporary files via UUID namespaces, added `@require_permission` on certificate endpoints, and emitted intrinsic event `_seq` for SSE streaming.
* **Visual Console Debugger Windowing & Verification Fallback Removal**: Added partial trace windowing banner for traces exceeding 10,000 events in Live Debugger and eliminated optimistic client-side `has_certificate` fallback claims in Verification Workflow.
* **3-Pillar Enterprise Verification Information Architecture**: Recomposed the Visual Console navigation hierarchy around three first-class objects: **Scenarios** (`/scenarios`, `/scenarios/compose`, `/suites`), **Runs** (`/runs`, `/reports`, `/debugger`, `/triage`), and **Evidence** (`/evidence/packages`, `/trust`, `/compliance`, `/publish`).
* **Guided 6-Stage New Verification Workflow**: Replaced legacy dashboard with an intuitive 6-stage wizard: *Connect Target Profile → Select Scenario/Suite → Review Resolved Config → Execute & Stream → Evidence-Linked Verification → Export Verification Package*.
* **Immutable Verification Package Exporter (`.agentv-package.json`)**: Implemented `/api/v1/evidence/packages/<run_id>` producing single-file, self-contained audit packages containing full scenario definitions, resolved execution manifests, trace SHA3 digests, assertion outcomes, and cryptographic provenance signatures conforming to NIST AI 100-1 and EU AI Act auditability guidelines.
* **Canonical 7-Tab Run Detail Screen**: Expanded run inspection into a dedicated 7-tab view (`Summary` | `Verification & Proofs` | `State & Tool Evidence` | `Telemetry Trace` | `VFS Sandbox` | `Policy & Guardrails` | `Artifacts & Package`), centering on the primary assurance verdict: *"Did this agent safely achieve the intended state transition?"*
* **Frontier Agent Target Connection Profiles**: Integrated target connection profiles for `OpenAI GPT-5.6`, `Anthropic Claude Opus 5`, `Google Gemini 3.1 Pro`, `Ollama DeepSeek-R1:70b`, and `Custom Enterprise Agent (Agent Protocol / REST)`.
* **Preflight Read-Only Resolved Manifest Inspector**: Added interactive pre-execution review boundary displaying content digests, multi-tenant workspace bindings, runtime timeouts, and active evaluators.
* **Fail-Closed Default-Deny RBAC & Route Authorization**: Gated client routing and state initialization behind default-deny `Viewer` role with server-authoritative `<ProtectedRoute />` boundary enforcement.
* **Primary Visual Console Canonical Mount**: Promoted `ui/visual-console` to the canonical SPA entrypoint mounted at `/`, `/scenarios`, `/reports`, `/editor`, `/debugger`, `/runner`, and `/trust`, preserving `/v2` strictly as a backward-compatible route.
* **Server-Authoritative Scenario Lifecycle State Machine**: Implemented `POST /api/scenarios/<id>/transition` governing authoritative `Draft` → `Validated` → `Ready` → `Published` → `Deprecated` state transitions with cryptographic scenario content hashing (`SHA3-256`) and audit history appending.
* **Two-Tier Status Model & Decision-First Reporting**: Enforced strict separation between process execution status (`RUNNING`, `EXECUTION_COMPLETED`, `EXECUTION_FAILED`, `STALLED`) and verified business outcomes (`VERIFIED`, `NOT_VERIFIED`, `POLICY_BREACH`, `UNVERIFIED`), prioritizing verified decision cards in the GUI run drawer.
* **Multi-Tenant ExecutionManifest Contract**: Expanded `ExecutionManifest` in `agentv_runtime.manifest` to bind `tenant_id` and `workspace_id` into canonical JSON serialization and deterministic SHA3-256 manifest ID calculation.
* **Run-Scoped Thread-Safe Visual Debugger Store**: Refactored `DebuggerStateStore` in `eval_runner/console/routes/system.py` to isolate runtime telemetry strictly per `(tenant_id, workspace_id, run_id)` with mutex synchronization and historical trace rehydration from vault logs.
* **Zero-Trust Micro-Frontend Extension Loader with Cryptographic SRI**: Upgraded `RemoteComponentLoader` to enforce byte-level Subresource Integrity (FIPS 202 `SHA3-256`, `SHA3-384`, `SHA3-512` and standard W3C SRI digests) using native Keccak-p sponge verification and WebCrypto fallback, ephemeral blob module instantiation, and strict origin policy boundaries.
* **Fail-Closed Execution Readiness & Preflight Probes**: Wired `/api/scenarios/readiness` to perform live validation of scenario schemas, agent endpoint reachability, and cryptographic sealers without synthetic bypasses.
* **Authoritative Cryptographic Badging in Runs & Reports**: Wired run detail drawer to query `/api/v1/verify/<run_id>`, rendering authentic cryptographic verification badges based on mathematical proofs.
* **Lossless Canonical Scenario Composer**: Visual scenario composer operates as a non-destructive patcher over the canonical AES JSON tree, eliminating semantic loss of custom node parameters and edge conditions.
* **Pure LiveDebugger Telemetry Parity**: Live debugger diff viewer binds directly to authentic runtime telemetry payloads (`expected_state`, `actual_state`, `divergence`), eliminating mock diff simulations.
* **Server-Authoritative Identity & RBAC**: Implemented `GET /api/auth/me` and `POST /api/auth/logout`, binding permissions strictly to server session claims and isolating developer persona switching to dev mode.
* **Canonical Execution Graph & Dagre Topology Rendering**: Formalized `execution_graph_node` and `execution_graph_edge` schema branches in `runs.schema.json` unified around the canonical identity triple (`scenario_node_id`, `execution_instance_id`, `parent_execution_id`); Live Debugger renders the Scenario DAG as the primary structural spine with real-time OpenTelemetry state overlays, Dagre LR layout, persistent coordinate caching (`nodePositionsRef`), and unified timeline scrubber centering.
* **Live Debugger Replay & State Parity Overhaul**: Implemented blue replay theme (`#3b82f6` border), `[REPLAYED]` badging, and compute split timing (`Pre: [x]s | Wait: [y]m | Post: [z]s`). Centralized `CANONICAL_TERMINAL_STATUSES` (including `STALLED`), planned scenario spine projection with dashed borders in executed mode before event arrival, responsive scrollable State Parity Inspector drawer, and stream control signal handling (`timeout`, `error`, `end`, `stream_end`).
* **Scenario Library Hygiene & Fixture Segregation**: Purged phantom `index` scenarios from catalog index scanning, tagged test/synthetic scenarios with `is_fixture: True`, and added dedicated segmented tabs ("Canonical Benchmarks", "Test & Synthetic", "All").
* **Resilient SSE Streaming with `Last-Event-ID` Catch-Up Replay**: Upgraded `/api/v1/runs/<run_id>/stream` with monotonic event sequence identifiers and durable trace replay for seamless reconnection without frame loss or duplication.
* **Server-Authoritative Verification Endpoint**: Promoted `/api/v1/runs/<run_id>/verify` to the sole authoritative source of verification truth, delegating directly to `TraceVerifier.verify_run_directory()`.
* **Monaco Canonical Source of Truth & Typed Assertions**: Implemented bi-directional document sync between embedded Monaco JSON/YAML editor and the AES canonical model, supporting typed assertions (`exact`, `regex`, `numerical_tolerance`, `json_schema`), conditional edge editing, and optimistic concurrency (`expected_revision_hash`).
* **PDF Report Generation**: Implemented ReportLab PDF generator in `pdf_service.py` extracting authentic metrics directly from `summary.json` and `run_manifest.json`.
* **Durable Job Store & Deterministic Output Binding**: File-backed `DurableJobStore` in `results/jobs/{job_id}.json` and explicit `results/batch_{job_id}` directory creation in `conductor.py` and `publication_suite.py`.
* **Complete 12-Interface Extension Family Ecosystem (`agentv_runtime.interfaces`)**: Expanded and wired all 12 public extension and storage interfaces:
  * `ExecutionBackend`: `InProcessExecutionBackend` with fail-closed resumption semantics.
  * `CheckpointStore`: `SQLiteCheckpointStore` and `LocalFileCheckpointStore`.
  * `SigningBackend`: `LocalEd25519SigningBackend`, `PQCSigningBackend` (FIPS 204 ML-DSA-65), and `NullSigningBackend`.
  * `ArtifactStore`: `LocalFileArtifactStore` with vault immutability sealing (`seal()`, `is_sealed()`).
  * `PolicyEvaluator`: `BasicFieldPolicyEvaluator` and declarative AST condition engine.
  * `AuthorizationBackend`: `SimpleAPIKeyAuthBackend` with key masking and principal listing.
  * `CatalogStore`: `LocalFileCatalogStore` for scenario discovery.
  * `RunStore`: `LocalFileRunStore` for manifest persistence.
  * `LeaderboardStore`: `LocalLeaderboardStore` for metric aggregation.
  * `MutationEngine`: `eval_runner.mutator.MutationService`.
  * `BoundedStateProvider`: Evidence boundedness contract with `query_bounded_reference`.
  * `ApprovalStore`: `ApprovalRequest` with `FileApprovalStore` and `SQLiteApprovalStore`.
* **Two-Tier Plugin Architecture**: Supported 17 native abstract `BaseEvalPlugin` lifecycle and interceptor hooks alongside dynamic event bus bridge dispatch (`on_<event_name.lower()>(context, **data)`).
* **Session Manager Subsystem Decomposition**: Decomposed monolithic `SessionManager` into 6 specialized subsystem components: `TurnStateManager`, `ToolExecutionCoordinator`, `SessionCheckpointManager`, `SessionApprovalManager`, `SessionStateParityManager`, and `SessionMetricsCalculator`.
* **Zero-Config Bootstrap Authentication & DevSecOps Hardening**: Automatically generates persistent 64-character SHA3-256 session key in `.aes/keys/bootstrap.key` (POSIX `0600` permissions) on first boot in development; fails fast with `RuntimeError` in production if keys are missing. Added non-blocking `LoginModal`, automatic fallback to read-only `Viewer` role, cold-load auth gate, explicit Flask session cookie security flags (`SameSite=Lax`, `HttpOnly=True`, `Secure`), and thread-safe sliding-window IP rate limiting on `/api/auth/login`.
* **Split Package Verification API & Standalone CLI Dispatcher**: Introduced `VerificationAuthority.verify_package_signature_only()` for lightweight cryptographic validation and `VerificationAuthority.verify_package_artifacts()` for deep multi-point forensic audit. Added independent `agentv verify-package` CLI command for offline verification of `.agentv-package.json` bundles with optional raw trace byte parity and scenario binding checks.
* **Pure RFC 8785 JSON Canonicalization Scheme (JCS)**: Implemented full specification-compliant JSON Canonicalization Scheme (RFC 8785) in `agentv_runtime.canonical` (`canonical_json_encode`, `canonical_json_dumps`), featuring UTF-16 code unit property sorting, ECMAScript 7.1.12.1 float stringification, and I-JSON strictness, backed by RFC test vectors.
* **Whole-Envelope Detached Trace Sealing & External Trust Root Mandate**: Enhanced `FlightRecorder` and `TraceVerifier` so that the trace seal detached signature covers the complete canonical envelope (`run_id`, `trace_digest`, `event_count`, `sealed_at`, `signer_identity`, `key_id`, `algorithm`, `metadata`) before signing. Mandated external trust root anchoring for manifests and packages, strictly returning `UNVERIFIED` for unanchored or self-generated ephemeral keys.
* **In-Archive ZIP Bundle Verification & Path Traversal Guards**: Added direct stream inspection of `.agentv-package.json` and trace files within `.zip` bundles, enforcing pre-extraction path traversal defenses that reject `..`, absolute paths, or Windows drive prefixes.
* **Centralized LLM Error Classifier & Resilience Wrapper**: Implemented `eval_runner.llm_resilience` providing typed domain exceptions (`LLMRateLimitError`, `LLMQuotaExceededError`, `LLMAuthenticationError`, `LLMTransientError`, `LLMInvalidRequestError`, `LLMModelNotFoundError`), heuristic classification across Google GenAI, OpenAI, Anthropic, and Ollama, and full-jitter exponential backoff retry runner (`execute_with_resilience`).
* **Dedicated Acceptance Testing Layer & Zero-Tolerance CI Release Gate**: Implemented schema-driven end-to-end acceptance testing in `tests/acceptance/` (`schemas/acceptance_case.schema.json`, decoupled `result.py` contracts, golden matrix `manifests/acceptance_matrix.yaml`, test suites) and a zero-tolerance CI release gate (`tools/ci/acceptance_gate.py`).
* **Documentation Platform v2 & Zero Demo Policy**: Completely redesigned and deployed Astro Starlight documentation platform (98 statically compiled pages, Pagefind search, sitemap) enforcing a strict Zero Demo Policy across all 60+ documentation topics and validated via automated CI Path & Link Sentinel (`docs/check_doc_paths.py`).

### Changed
* **Authoritative Contract Package Inversion**: Elevated `agentv_runtime` from a re-export facade to the root authoritative contract package defining native abstract base classes for all 12 extension and storage interfaces, with `eval_runner` implementing them.
* **Subsystem Contract Versioning**: Published all 6 authoritative contract versions in `eval_runner` and `agentv_runtime`:
  * `__runtime_api_version__ = "2.0"`
  * `__plugin_api_version__ = "1.0"`
  * `__config_schema_version__ = "1.0"`
  * `__aes_schema_version__ = "1.4"`
  * `__certificate_schema_version__ = "3.0.0"`
  * `__event_schema_version__ = "1.0"`
* **Lightweight OSS Packaging Diet**: Decoupled heavy optional dependencies (`sentence-transformers`, `datasets`, `google-genai`, `langchain-openai`, `langsmith`, `pypdf`, `python-docx`, `weasyprint`, `reportlab`, `cyclecore-pq`, `GitPython`) into `[project.optional-dependencies]`.
* **Standardized SHA3-256 Cryptographic Primitives**: Standardized all forensic content hashing, session keys, trace seals, and evidence ledgers strictly on SHA3-256 (FIPS 202) over RFC 8785 JCS canonical bytes.
* **Session Secret Key Derivation**: Console session signing key derived via pure SHA3-256 (`app.secret_key = crypto.checksum(api_key or secret_key_env)`), producing a 64-character hex digest.
* **Certificate Schema Version Synchronization**: Synchronized `Attestation.certificate_schema_version` default from `"2.0.0"` to `"3.0.0"`.
* **Frozen Immutable `VerificationResult`**: Converted `VerificationResult` to `@dataclass(frozen=True)` matching `ExecutionResult` and `EvaluationResult`, preventing mutation after verification decision and certificate binding.
* **4-Tier Dependency Model & Automated Compliance Tooling**: Structured `pyproject.toml` into Core runtime (20 packages), Direct Providers (`provider-gemini`), Frameworks (`framework-*`), and LangChain wrappers (`langchain-*`), declaring `langchain-google-genai`. Upgraded `tools/ci/sync_compliance.py` with `tomllib` parsing and automated `requirements.txt` mirroring.

### Fixed
* **Required-Oracle Fail-Closed Compilation Semantics**: Removed exception suppression in `compile_required_oracle_ids()` in `eval_runner/runner.py`. Scenario compilation and oracle discovery fail fast and closed if assertions or criteria are malformed, preventing unmonitored execution runs.
* **Plain Execution Manifest vs. Verification Certificate Discrimination**: Implemented `_is_plain_execution_manifest()` in `eval_runner/verifier.py` and `CertificationService`, rejecting uncertified runs with `UNVERIFIED` and `failure_reason: "Certification not issued"` instead of false positives or unhandled exceptions.
* **Mutation Failure Policy Schema Preservation**: Eliminated dictionary assignments to `scenario["failure_policy"]` across `rollback_failure`, `duplicate_commit`, and `commit_after_cancel` in `eval_runner/mutator.py`, strictly setting node/metadata flags and preserving string enum contracts.
* **Elimination of Caller Status/Score Overrides in Certification**: Removed caller parameter overrides in `TraceVerifier.sign_trace()` and `eval_runner/handlers/evaluation.py`, ensuring verdicts are derived exclusively from immutable execution events.
* **Direct Provenance Enforcement & Carrier Fallback Elimination**: Mandated complete direct provenance in `TraceVerifier.verify_trace()` (`is_complete_provenance = True`), rejecting carrier fallback assertion sequences with `DirectProvenanceViolation`.
* **Intrinsically Fail-Closed Trace Persistence in Certification Mode**: Fixed `FlightRecorder` so that any persistence failure during certification or attestation mode immediately aborts the run to `CERTIFICATION_FAILED`, tracks failed runs, and strictly prohibits seal or package generation.
* **Authoritative Cryptographic Status in Reporter**: Fixed `eval_runner/reporter.py` to derive `is_verified` exclusively from cryptographic verification proof rather than disk file existence.
* **Submodule Re-Export Propagation in Mutation Testing Loader**: Resolved surviving mutants in re-exported packages by updating the in-memory loader to pre-register modules in `sys.modules` and synchronize re-exported package attributes before importing parent packages.
* **Acceptance Subprocess Timeout Hardening**: Configured 180s default execution timeout and `AGENTV_ACCEPTANCE_TIMEOUT` environment variable in `AgentVAcceptanceRunner._exec` to prevent false-negative timeouts under heavy parallel worker loads.
* **Google GenAI AFC Warning Elimination & Quota Handling**: Eliminated automatic function calling warnings and handled 429 quota exhaustion gracefully via the centralized resilience wrapper.
* **Ephemeral Key Fallback Elimination**: Removed obsolete ephemeral `os.urandom` session key fallback in `eval_runner/console/app.py`, enforcing persistent bootstrap key usage.
* **Injected Extension Backend Bypass in InProcessExecutionBackend**: Eliminated all bypass paths in `InProcessExecutionBackend.submit()` and `resume()` by injecting the complete enterprise dependency graph (`artifact_store`, `checkpoint_store`, `policy_evaluator`, `signing_backend`, `config_resolver`, `run_store`, `execution_backend`) and passing configured runner instances into scenario execution.
* **Lossless Config-Mesh Namespace Preservation**: Resolved config mesh discarding unknown keys by introducing formal typed namespaces (`core`, `adapters`, `plugins`, `policies`, `custom_settings`) in `ResolvedRuntimeConfig` and `ConfigResolver`, with deterministic SHA3-256 hashing across all namespaces without data loss.
* **HITL Resumption Race Condition & State Machine Guards**: Hardened `InProcessExecutionBackend.resume()` with strict execution state machine validation, unconditionally rejecting `RUNNING` executions (preventing duplicate worker threads) and terminal states (`COMPLETED`, `FAILED`, `ABORTED`, `CANCELLED`) unless explicit `force_recovery=True` protocol is specified.
* **Tool Definition Truthiness Routing**: Fixed `if tool_name not in all_tool_defs:` in `tool_sandbox.py`, ensuring tools defined as empty dicts (`{}`) execute standard mock behaviors instead of simulator fallbacks.
* **Console Test Fixture Isolation**: Hardened `console_jail` fixtures across all console route test modules with per-worker isolated directories (`aes_console_test_jail_{worker_id}`).
* **Cold Process Restart Checkpoint Durability**: `InProcessExecutionBackend.status()` now consults the durable `CheckpointStore` on cold reads (when `run_id` is absent from process-local memory), and `resume()` validates checkpoint state from `CheckpointStore` when in-memory state is absent, enforcing state machine guards across full process restarts.
* **Resumed HITL Node Completion State Parity**: Synthesized `hitlResumeMap` entries from `approval_resolved (decision: APPROVED)` events in Visual Console debugger logic, preventing premature demotion of resumed, completed nodes to stalled states.
* **State Parity Inspector Viewport Expansion**: Restructured Live Debugger right inspector drawer with flex-expanding scrollable layout, eliminating arbitrary `max-h-[220px]` parameter restrictions.
* **OpenAPI Health Probing & Dual Normalization**: Fixed OpenAPI adapter preflight health checking using `urljoin(endpoint, "/health")` and unified non-AgentV response extraction into `final_answer`.

### Security
* **Destination-IP Validation & Anti-DNS Rebinding**: Enforced strict destination-IP validation across all HTTP adapters and LLM providers under `AIRGAPPED_MODE=true`, preventing SSRF and DNS rebinding leaks.
* **Console Content Security Policy Hardening**: Enforced strict script execution `'self' blob:`, stripped external CDNs in airgap mode, and supported operator CSP overrides via `CONSOLE_CSP_SCRIPT_SRC` and `CONSOLE_CSP_CONNECT_SRC`.
* **WORM Physical Storage Verification**: Enforced fail-closed verification of physical immutable WORM storage when claimed or mandated (`REQUIRE_IMMUTABLE_WORM=true`).
* **Session Cookie Security & Rate Limiting**: Enforced `HttpOnly=True`, `SameSite=Lax`, automatic `Secure=True` in production, and sliding-window IP rate limiting on `/api/auth/login`.
* **Zero-Config Bootstrap Key Governance**: Automatically generated high-entropy persistent key in `.aes/keys/bootstrap.key` with POSIX `0600` permissions in development; strictly enforced explicit production keys in `AGENTV_ENV=production`.
* **In-Archive ZIP Stream Safety**: Neutralized Zip Slip attacks by verifying `.agentv-package.json` and trace streams directly in memory without disk extraction, rejecting path traversal markers (`..`).
* **Centralized Path Safety (`SafeRunPathResolver`)**: Enforced jail boundary checks across all storage, run, and catalog operations.
* **Fail-Closed Cryptographic Enforcement on Key Absence**: Enforced strict `RuntimeError` on missing signing keys when `EVAL_REQUIRE_SIGNING=true` or `AUDIT_LEVEL >= 2`.

---


## [1.9.0] - 2026-08-17

### Added
* **Public Extension Families**: Defined standard Python abstract base classes (`abc.ABC`) under `eval_runner.interfaces` and exported via the `agentv_runtime` package:
  * `ExecutionBackend` (`submit`, `status`, `cancel`, `resume`) for neutral evaluation run orchestration.
  * `CheckpointStore` (`save`, `load`, `delete`, `list_checkpoints`) for session checkpoint persistence.
  * `SigningBackend` (`sign_payload`, `verify_signature`) for cryptographic trace sealing.
  * `ArtifactStore` (`store_artifact`, `get_artifact`, `exists`, `list_artifacts`) for evaluation artifact lifecycle.
  * `PolicyEvaluator` (`evaluate_policy`, `validate_policy`, `PolicyEvaluationResult`) for modular policy adjudication.
  * `AuthorizationBackend` (`validate_token`, `check_permission`, `AuthPrincipal`) for access control.
* **Resolved Runtime Config & ConfigResolver Boundary**: Implemented `ResolvedRuntimeConfig` model with deterministic SHA3-256 hash digest (`config_hash`) for Processing Integrity evidence, and hierarchical `ConfigResolver` merging baseline defaults, file-based configuration (`.aes/config/*.json`), environment variables, and runtime overrides.
* **Modular `session.py` Subsystem Decomposition**: Refactored monolithic session execution into dedicated, independently testable subsystem managers under `eval_runner/session_components/`:
  * `TurnStateManager`: Turn sequence tracking, token consumption metrics, and message history.
  * `ToolExecutionCoordinator`: Sandboxed tool execution, simulator dispatch, and telemetry.
  * `SessionCheckpointManager`: Durable session state checkpointing via `CheckpointStore`.
  * `SessionApprovalManager`: Human-in-the-loop (HITL) approval requests, tokens, and pause/resume coordination.
* **Subsystem Contract Versioning**: Published independent version metadata attributes in package root:
  * `__runtime_api_version__ = "1.9"`
  * `__plugin_api_version__ = "1.0"`
  * `__config_schema_version__ = "1.0"`
  * `__aes_schema_version__ = "1.4"`
* **OSS Reference Implementations**: Shipped production reference backends in `eval_runner/reference/`:
  * `InProcessExecutionBackend`: In-process local execution backend.
  * `SQLiteCheckpointStore`: Durable SQLite-backed state persistence.
  * `LocalFileArtifactStore`: Local filesystem artifact storage.
  * `BasicFieldPolicyEvaluator`: Numeric boundary, required-field, and constraint policy evaluator.
* **Package Integration (`agentv_runtime`)**: Introduced the `agentv_runtime` package alias and public contracts surface, enabling seamless zero-touch integration by downstream control planes without forking or monkey-patching.

## [1.8.0] - 2026-08-16

### Security
* **Path Traversal Jail Protection**: Hardened `mutate_scenario` and `spec_to_eval` with `is_path_safe` jail boundary checks, preventing arbitrary file write and overwrite attacks outside configured scenario roots.
* **Policy Sandbox Numeric Constraint Generalization**: Generalized numeric constraint checks across arbitrary parameter keys and nested structures rather than hardcoded `amount`/`transfer` fields.
* **Fail-Closed Cryptographic Enforcement**: Enforced strict fail-closed exceptions (`RuntimeError`) on signature corruption or invalid key paths under `AUDIT_LEVEL >= 2`.

### Fixed
* **Multi-Attempt Report Aggregation**: Corrected reporting plugins to retain and aggregate all evaluation attempts in multi-attempt execution runs without dropping prior attempt telemetry.
* **Evidence Sealing Order & Provenance Pipeline**: Strictly enforced execution pipeline ordering: `Execute -> Collect -> Seal -> Compute Ledger -> Physical Hash -> Manifest -> Sign`.
* **Deterministic Trace Fingerprinting**: Eliminated non-deterministic wall-clock `strftime` stamps from core fingerprint hashing algorithms.
* **HITL Restart Durability & Accurate Remaining Timeouts**: Added persistent `resumption_token`, `resumed_from_db` tracking, auto-migrating SQLite schemas, and accurate remaining timeout calculations across process restarts.
* **Statistical Bounds & Failure Denominators**: Corrected percentile index calculation at $p=100$ and standardized the failure distribution denominator to total attempts $N_{\text{total}}$.
* **Simulator Tool Routing**: Fixed tool routing membership checks to prevent dispatching empty or unregistered tool definitions to simulators.

### Added
* **Golden Verification Corpus (`tests/golden/`)**: Built an immutable 9-suite, 14-test regression verification corpus validating all 12 defect remediations.

## [1.7.3] - 2026-08-14

### Added
* **Dynamic Navigation Manifest & Runtime Module Federation**: Introduced generic, zero-recompilation micro-frontend extensibility in `ui/visual-console/src/App.tsx`. Ingests `GET /api/nav` via TanStack Query and dynamically deep-merges plugin navigation items with built-in groups (`mergeNavManifest`).
* **Runtime Micro-Frontend Remote Component Loader**: Implemented `RemoteComponentLoader` with `RemoteErrorBoundary` in `App.tsx` loading standalone ESM plugin bundles on demand via standard dynamic `import(/* @vite-ignore */ entryUrl)` without requiring build-time coupling or core frontend recompilation.
* **Rich Navigation Metadata & Visual Badging**: Added support for sidebar badges (e.g. `LIVE`, `HOT-RELOAD`, `FLEET`, `APM`, `◆ ENT`), tier markers (`tier === 'enterprise'`), Lucide dynamic string icon resolution (`resolveIcon`), external URLs (`<a>` tags), and item-level RBAC role gating (`required_role`).
* **100% Mutation Testing Sentinel Assurance**: Achieved 100% AST mutation detection rate (91 killed, 0 timeout, 0 survived, 29 incompetent/annotation-only) across all 120 mutation points in `eval_runner/verifier.py`, `eval_runner/tool_sandbox.py`, and `eval_runner/utils/base.py`.
* **Cross-Platform Process Singleton Locking**: Added `.mutation_testing.lock` mutex with emergency worktree auto-restoration in `tools/ci/run_mutation_tests.py` to prevent race conditions and test corruptions under parallel/concurrent invocations.

### Fixed
* **Interceptor Pipeline Recursion & Sequence Bounds**: Added exhaustive test coverage for passthrough, failing, and skipped interceptor pipeline depth and sequence increments (`make_next(index + 1, depth + 1)`).
* **Multi-Run Certificate & Sandbox Directory Creation**: Verified nested directory creation and `exist_ok=True` retention across distinct run IDs for both `TraceVerifier` report certificate backups and `ToolSandbox` workspace/jail directories.

## [1.7.2] - 2026-08-11

### Added
* **Parallelized Industry Scenario Corpus Validation**: Re-anchored `test_scenario_compliance.py` to validate all 5,040+ AES scenario files under `industries/` using `@pytest.mark.parametrize` for full `pytest-xdist` parallel worker distribution, strict exception hygiene (`json.JSONDecodeError`, `ValidationError`), multi-version schema dispatch, and a disk-count sentinel check.
* **Independent Cryptographic Verification Oracle**: Implemented `IndependentTraceOracle` in `tests/unit/core/test_golden_verifier_matrix.py` using stdlib `hashlib` and raw `cryptography` Ed25519 and ML-DSA-65 (PQC) primitives, completely decoupled from `TraceVerifier`.
* **7-Stage Golden Verify-After-Tampering Matrix**: Implemented 7-stage verify-after-tampering matrix in `test_golden_verifier_matrix.py` verifying detection of event payload alterations, line deletions, unauthorized event insertions, sequence swaps, signature corruptions, and identity key substitutions.
* **Synchronized TOCTOU Barrier Race & Security Isolation**: Added `tests/security/test_sandbox_adversarial_bypass.py` testing `ToolSandbox` against path traversal jail escapes, prompt injection state immutability, subshell stripping, 50-level deep nested JSON payloads, and an `asyncio.Event` barrier synchronized TOCTOU permission revocation race test (`test_sandbox_toctou_race_condition`).
* **High-Value Property-Based Invariants**: Added `test_property_unauthorized_state_mutation_invariant` to `tests/property/test_schema_property_based.py` verifying unauthorized state mutation protection under property-based fuzzing.
* **Parameterized Framework Adapter Matrix**: Expanded `tests/contract/test_adapter_contracts.py` into a parameterized contract matrix across `LangChain`, `OpenAI`, `Ollama`, `OpenAPI`, `Grok`, and `AG2` adapter plugins verifying connection pooling, exponential backoff retries (429/503 status codes), max retries exception escalation, and `AESCallbackHandler` telemetry.
* **Hardened SLA Latency Gates & 1,000 Session Scaling**: Enforced explicit mean latency SLA gate assertions (`assert mean_latency_sec < 0.005`) in `tests/performance/test_interception_benchmarks.py` (<5ms SLA) and added `test_1000_session_concurrency_scaling` evaluating 1,000 concurrent evaluation sessions with 100% unique run IDs and zero resource leaks.
* **Boundary Fault Injection Chaos Suite**: Implemented `tests/chaos/test_chaos_resilience.py` with boundary fault injection across LLM transport HTTP 500s, simulator runtime process crashes, missing WORM trace files, and invariant checks ensuring evaluation failures never silently convert to verification successes.
* **Cross-Platform Security Hardening**: Updated `is_path_safe` in `eval_runner/utils/base.py` to normalize Windows drive letters (`C:\...`) and UNC paths (`//...`) on POSIX and Windows systems.
* **Documentation Sentinel Script**: Created `docs/check_doc_paths.py` to verify all markdown documentation path references against physical disk files and integrated it into GitHub Actions CI workflow.

### Fixed
* **Documentation & Hype File Relabeling**: Regenerated `TESTING.md` to reflect active codebase structure and commands. Renamed marketing hype test files in `dataproc_engine/tests/` to reflect actual technical behavior (`test_dataproc_parity_benchmarks.py`, `test_signal_veracity_benchmarks.py`, `test_sector_quality_standards.py`).
* **CI Coverage Threshold Enforcement**: Configured `fail_under = 85` in `.coveragerc` and `--cov-fail-under=85` in `.github/workflows/ci.yml`.
* **Healthcare Scenario Schema Compliance**: Updated `industries/healthcare/scenarios/new-scen.json` to include required `evaluation` property.

## [1.7.1] - 2026-08-06

### Added
*   **Thread-Safe Runs Cache Daemon**: Replaced synchronous disk scans with a thread-safe background runs caching manager (`RunsCache`) polling differentially every 1s and serving list/stream queries instantly from memory.
*   **ZIP Bundle Integrity Verification**: Supported drag-and-drop ZIP bundle verification uploads matching internal files against their SHA3-256 hashes and verifying Ed25519 signatures.
*   **Live Debugger React Flow Canvas Refinements**: Formatted timeline nodes into wrapped rows (max 4 per row) with automatic canvas fits, click-to-zoom timeline transitions, and direct "Isolate Root Cause" target actions.
*   **Forensic Timeline Details**: Expanded log event cards to include precise sequence numbers, turn indices, a manual stream reconnect button, and a quick-action "Go to Root Cause Turn" AI drawer trigger.
*   **Robust Runs Cache Pruning**: Configured runs cache to clean up deleted/pruned traces from memory, preventing missing files from cluttering console selectors.

### Fixed
*   **Conductor Absolute Imports**: Resolved publication suite python script execution crashes by forcing absolute imports and pre-loading PYTHONPATH in child processes.
*   **Compliance Pack Publish 404 Gate**: Restructured publish handler to return 404 when publishing unknown compliance pack IDs.
*   **Fuzzer Catalog ID Resolution**: Fixed programmatic fuzzer mutation crashes by supporting scenario ID catalog lookups.
*   **Privacy Path Sanitization**: Masked absolute project path targets to relative markers in doctor diagnosis endpoints and job logs.
*   **Pytest Cache Thread Bypass**: Prevented `RunsCache` from starting its background update loop thread under pytest, avoiding file lock contentions and cross-test cache pollution.

## [1.7.0] - 2026-07-31

### The Integrated Visual Console (Native GUI) and Compliance Engine Release
*   **The Integrated Visual Console (Native GUI)**: Introduced the new official visual interface (`/v2`) serving as the central Verifiable Agent OS dashboard, compiling cleanly into production assets. Key features include:
    *   *Scenario Library & Canvas Composer* (`ScenarioLibrary.tsx`, `ScenarioComposer.tsx`): Supports canvas-based React Flow visual scenario mapping, nodes configuration, and edge connections with a direct YAML/JSON editor synchronization.
    *   *Evaluation Runner* (`EvaluationRunner.tsx`): Interactive dispatcher console with sliders for max turns, judge counts, and target selector controls.
    *   *Live Debugger & State Parity Diff* (`LiveDebugger.tsx`): Real-time SSE streaming logs timeline, visual highlight nodes in React Flow, and side-by-side Git-style state diffs via `ReactDiffViewer` to detect state divergences.
    *   *Triage Dashboard & AI Diagnostics* (`Triage.tsx`, `TraceExplain.tsx`): Aggregate failure trends classified under Logic, Policy, or Security categories, coupled with interactive AI triage recommendation engines.
    *   *Real-Time HITL Approvals Queue* (`HITLQueue.tsx`): Async-unblocked reviewer cockpit showing active suspensions, countdown SLA clocks, and required rejection reason audit entries.
    *   *Spec-to-Eval Importer* (`SpecToEvalImporter.tsx`): Drag-and-drop Markdown requirements translator that converts PRDs to scenarios and loads drafts directly into the Composer.
    *   *Adversarial Scenario Mutator* (`AdversarialMutator.tsx`): Generates keyboard typos, vagueness ambiguity, and instruction injections on existing scenarios with side-by-side prompt previews.
    *   *Trust Center & Reports*: Real-time signature validator verification checks and WeasyPrint/ReportLab dual PDF generators.
*   **Granular PBAC Model & Dynamic Persona Swapping**: Linked a dynamic Role selection dropdown in the Header toolbar supporting 4 roles (System Admin, Compliance Auditor, Scenario Designer, MultiAgentOps Eng.) mapping to granular backend permissions.
*   **Async HITL Worker Refactor**: Re-engineered `SessionManager._handle_hitl` to suspend runs in a restart-resilient SQLite-backed registry (`hitl.db`) instead of blocking threads or stdin. Added automated test safeguards to bypass review loops during testing suites.

## [1.6.8] - 2026-07-24

### SHA-3 Cryptographic Standard & Unified Hash Utility Layer
*   **Unified SHA-3 Family**: Standardized the harness security architecture on the FIPS 202 SHA-3 algorithm family. Content verification and file signature generation leverage SHA3-256, while variable-length identifiers and ZES pre-images utilize SHAKE-256 XOF.
*   **Centralized Hashing Utility (`crypto.py`)**: Introduced `eval_runner/utils/crypto.py` to route all cryptographic hashing operations through a single, canonical utility layer.
*   **VC v3.0.0 Schema Update**: Updated `spec/vc/vc.schema.json` and verification pipelines to replace `"sha256"` with `"trace_hash"` and `"hash_algorithm"`.
*   **Loader & Test Suite Parity**: Upgraded all 12 industry data loaders in `dataproc_engine/providers` to use `crypto.record_id` and `crypto.checksum`, passing 100% of the unified test suites.

## [1.6.7] - 2026-07-22

### Core Enum Expansion & Enterprise Failure Taxonomy Alignment
*   **Expanded `FailureCategory` StrEnum**: Expanded `FailureCategory(StrEnum)` in `eval_runner/taxonomy.py` with native core support for `POLICY_KNOWLEDGE_STALENESS`, `LOGIC_OBJECTIVE_MISALIGNMENT`, and `SECURITY_IDENTITY_HITL_FAILURE` failure codes.
*   **Forensic Triage Engine Suggestions**: Updated `eval_runner/triage.py` with diagnostic suggestion templates in `SUGGESTION_TEMPLATES` for knowledge staleness, objective misalignment (specification gaming), and HITL authorization failures.
*   **100% Test Coverage Hardening**: Updated `tests/unit/core/test_core_taxonomy.py` and `tests/unit/core/test_taxonomy_coverage_booster.py` with complete behavior, string value, and triage template tests, achieving 100.00% statement and branch test coverage on `eval_runner/taxonomy.py`.
*   **Documentation & Specification Sync**: Updated `docs/src/content/docs/spec/taxonomy.md` and `docs/src/content/docs/evaluator/taxonomy.md` reference tables and lists across Logic, Policy, and Security domains.

## [1.6.6] - 2026-07-07

### Agnostic Wire Protocol & Declarative Config Mesh Payload Wiring
*   **Core Engine Payload Isolation**: Stripped harness-internal context keys (`input_payload`, `metadata`, `protocol`, `turn`, `history`) from crossing the network boundary by default in `engine.py`, aligning the HTTP wire payload to match a clean natural language task prompt (`task_description`).
*   **Protocol-Aware Payload Building**: Added a special protocol-aware check in `engine.py` to preserve passing `input_payload` as the POST body exclusively for the `openapi` protocol/adapter.
*   **Deep-Sync of Routing Manifest Overrides**: Updated `session.py` to copy all fields from the resolved registry manifest (`self.session_metadata`) into `TurnContext.metadata`. This allows the engine and adapters to read and react to declarative routing overrides.
*   **Declarative Payload Templates**: Added support in `engine.py` to dynamically render wire payloads according to a declarative `payload_template` defined in the config mesh (`manifest.json`) metadata. This permits mapping standardized fields to custom schemas (e.g. `input` and `context` required by `agentv-tester`) with zero hardcoded agent logic inside the harness.

## [1.6.5] - 2026-06-30

### Pluggable Witness, Quiescence, and Test Coverage Hardening
*   **Asynchronous Event Dispatching & OTel Context Propagation**: Enabled asynchronous event subscriber execution via a thread pool or task queue in `events.py` to eliminate telemetry-induced turn latency. Implemented parent-child OpenTelemetry context propagation across execution threads and async tasks, and added a `.flush()` method to block until background tasks complete.
*   **Simulator Middleware & Pluggable Jail Providers**: Introduced a `SimulatorMiddleware` interface and execution pipeline inside `BaseSimulator`. Added the `BaseJailProvider` interface in `simulators.py` with a mandatory `.cleanup(run_id)` method to allow sandbox environment resource teardowns, and updated `TerminalSimulator` to delegate execution to the pluggable `BaseJailProvider` (defaulting to `SubprocessJailProvider`).
*   **Triage & Failure Taxonomy Hooks**: Standardized triage schemas via `TriageContext` and `TriageReport` in `triage.py`. Exposed failure classifier registries to let extensions register custom/LLM classifiers, and updated `FailureTaxonomy` to allow specialized priority forensic analyzers to execute before core diagnostics.
*   **Deterministic Quiescence & Timeout Guard**: Added `async def quiesce(self) -> None` hook to `BaseSimulator`. Configured `ToolSandbox` to execute the quiesce hook immediately after simulator tool execution, wrapped in a strict `5.0s` timeout guard (`asyncio.wait_for`) to prevent unresponsive simulators from stalling the runner.
*   **ShimResultProxy & Memory Partitioning**: Implemented `ShimResultProxy` inheriting from `dict` in `simulators.py` to partition secure metadata (like cryptographic keys or OTel telemetry DNA) from the guest environment, returning only standard status/message fields during dict traversal/inspection.
*   **Lazy Witness Abstractions**: Standardized post-evaluation audit checks by introducing `BaseWitness` and `VerificationResult` schemas in `triage.py`.
*   **100% Target Test Coverage Hardening**: Hardened the unit and branch coverage through extensive mock updates and edge case tests.

## [1.6.4] - 2026-06-13

### Trend Analyzer & Concurrency Hardening
*   **Trend Analyzer for Historical Runs**: Introduced a new trend analysis engine (`eval_runner/trend.py`) and CLI integration (`eval_runner/handlers/analysis.py`) to aggregate and graph metrics (such as performance indices, failure rates, and attribution shifts) over time across historical test runs.
*   **Thread & Context Isolation**: Hardened concurrent async execution loops in `mutator.py`, `pipeline.py`, and `verifier.py` with strict context-local validation to guarantee robust isolation and prevent cross-run state pollution under highly concurrent workloads.
*   **Robustness & Zero-Trust Verification Tests**: Expanded the test suite to verify Zero-Trust baseline boundaries and safeguard registry mocking against import mismatches or module-level caching issues under pytest.

## [1.6.3] - 2026-05-23

### Core Interceptor Pipeline & Sandbox Isolation Architecture
*   **Dynamic Verifier Pipeline**: Introduced the `TraceVerificationInterceptor` abstract interface and thread-safe `VerificationService` registry within `eval_runner/verifier.py`. This enables hot-swapping trace signing logic and lets enterprise extensions hook into HSMs or secure KMS vaults without exposing raw private key bytes to the core environment.
*   **Zero-Trust Sandbox Interception**: Implemented `ToolSandboxInterceptor` and a centralized `ToolSandboxService` registry within `eval_runner/tool_sandbox.py`. All tool executions (`ToolSandbox.execute`) are now routed through `tool_sandbox_service.isolate`, allowing dynamic auditing, mutation, and filtering of inputs and outputs.
*   **Asynchronous State Isolation**: Replaced standard thread-local storage (`threading.local`) with `contextvars.ContextVar` in `ToolSandboxService` to enforce strict coroutine-local task isolation, preventing state pollution and leakage across concurrent async execution loops.
*   **Safe Context Restoration**: Wrapped trace signing in a strict `try...finally` block within `TraceVerifier.sign_trace` to guarantee that transient metadata (`signing_context`) is popped, eliminating potential memory leaks and context leakage.
*   **Thread-Safe Registry Reset Hooks**: Exposed formal `reset()` methods on `VerificationService` and `ToolSandboxService` to prevent state pollution between unit test files.
*   **Comprehensive Pipeline Testing**: Delivered premium unit test suites (`test_verifier_pipeline.py` and `test_tool_sandbox_pipeline.py`) validating interceptor chaining, context manager overrides, parameter injection, auditing, and preemptive execution bypasses.

## [1.6.2] - 2026-05-15

### Hybrid PQC Signing & Forensic Security
*   **Hybrid PQC Signing (ML-DSA-65)**: Integrated the NIST-standardized Post-Quantum Cryptography (PQC) algorithm (ML-DSA-65) for non-repudiable signing. Certificates now feature a dual provenance chain: classical (ED25519) and quantum-resistant (ML-DSA-65).
*   **Zero-Exposure Signing (ZES)**: Implemented the ZES pattern via `cyclecore-pq` (v0.3.0). Local SHAKE-256 digests are computed locally, ensuring sensitive audit data never leaves the system boundary during PQC signing.
*   **Cryptographic Utility Expansion**: Added `compute_shake256_digest` to `forensics.py` and extended `IdentityService` to manage remote PQC providers.
*   **Standardized Configuration**: Introduced `PQC_ENABLED`, `PQC_PROVIDER`, and CycleCore-specific environment variables for flexible, secure-by-default deployment.

### CLI & Compliance Hardening
*   **Centralized PQC CLI Controls**: Extended the `agentv` CLI with unified `--pqc` and `--no-pqc` flags across `run`, `evaluate`, `gate`, `verify`, `certify`, and `report` commands. Implemented a centralized `_add_pqc_args` helper to ensure interface consistency.
*   **Internalized Compliance Orchestration**: Introduced `eval_runner/compliance.py` featuring a production-grade `ComplianceService`. This internalizes the logic for PQC status verification and behavioral branching (Strict vs. Fallback modes), resolving external dependency issues in CI environments.
*   **Industrial Test Parity**: Expanded the unit test suite with `test_pqc_cli_handlers.py` and `test_compliance_pqc.py` for hybrid-signature validation and strict-mode gating.

## [1.6.1] - 2026-05-10

### Industrial Hardening & Ecosystem Branding
*   **AG2 Framework Rebranding**: Completed the transition from AutoGen to **AG2**. Updated all adapter registrations to support `ag2://`.
*   **"No-Masking" Error Policy**: Hardened adapter infrastructure to strictly propagate `ImportError` when required SDKs (LangChain, LangGraph, CrewAI, AG2) are missing. This ensures transparent environment reporting and prevents silent fallbacks to simulation in production.
*   **CI/CD Stabilization**: Refactored the test suite to use `patch.dict(sys.modules, ...)` for robust environment isolation, resolved registry discovery regressions, and fixed unawaited coroutine warnings in mock-heavy test scenarios.
*   **Industrial Compliance Notice**: Integrated the **Forensic Trust Protocol v3.0.0** governance baseline and configured `pyproject.toml` to filter noisy upstream deprecation warnings.

## [1.6.0] - 2026-04-26

### Modern Agent Support & Robust Metrics
*   **Streaming Agent Support (SSE)**: Implemented native `sse_http_adapter` for `text/event-stream` interaction. Features automated chunk accumulation, JSON normalization, and graceful handling of malformed streams.
*   **Robust Semantic Judging (Luna-Judge)**: Upgraded the LLM-as-Judge layer with enhanced regex-based score extraction and fallback Jaccard similarity heuristics. Handles reasoning-heavy agent responses with high fidelity.
*   **Protocol Trace Observability**: Enhanced `SessionManager` to emit `STEP_START` events for every agent turn, enabling the `protocol_sequence` to track interaction protocols (`sse`, `http`) in forensic traces.
*   **Adapter Interface Standardization**: Standardized all internal and plugin-based adapters to use a unified `(payload, endpoint=None)` signature, ensuring ecosystem-wide stability.
*   **Security Policy Modernization**: Updated the default adapter policy to include `sse` in the `active_protocols` whitelist.
*   **Engineering Hygiene**: Removed legacy `[PROBE: ...]` debug prints from production code and purged dead testing artifacts (`mock_agent_api.py.unused`).
*   **Comprehensive Documentation Audit**: Fully updated the Triage Engine spec, Forensic Ledger schema, and User Manual to reflect the v1.6.0 feature set.

## [1.5.1] - 2026-04-24

### Industrial CLI Extension Architecture
*   **Zero-Touch Extension Discovery**: Implemented a standard Python Entry Points pattern (`agentv.extensions`) for dynamic, decoupled CLI command registration. This allows Enterprise extensions to plug into the Core CLI without modifying a single line of Core code.
*   **Unified Functional Dispatcher**: Replaced the monolithic 200+ line `if/elif` command-handling block with a data-driven functional dispatch system. All commands (Core and external) now share a unified execution protocol.
*   **Lazy-Loading Optimization**: Introduced a PEP 562-inspired lazy-loading layer for command handlers. This ensures that the CLI remains hyper-responsive (<500ms startup) while decoupling heavy internal dependencies like `engine` and `simulators`.
*   **Industrial Discovery Isolation**: Hardened the discovery loop to gracefully handle extension load failures, ensuring that a single broken external plugin cannot crash the main CLI environment.
*   **Native Async Dispatching**: Enhanced the dispatcher to natively detect and execute asynchronous command handlers, providing seamless integration with the core engine's async lifecycle.
*   **Standardized Handler Signature**: Formalized the command handler protocol (`handle_command(args) -> int`) to ensure consistent exit-code propagation and error handling across the entire ecosystem.

## [1.5.0] - 2026-04-12

### Deep Forensics & Core Refinement
*   **Deep Forensics Engine (v1.5.0)**: Refactored the taxonomy engine from a monolithic heuristic scanner into a pluggable, registry-based diagnostic platform.
*   **Reduced Core Dependencies**: Eliminated the requirement for `sentence_transformers` and `numpy` dot-product logic in the Core harness.
*   **Centralized State Observability**: Migrated `state_read` and introduced `state_write` event emissions into the `SharedStateRegistry`, ensuring 100% forensic coverage for data lineage and industrial taint tracking.
*   **Granular Taint Tracking**: Enhanced the `SharedStateRegistry` to accept a centralized `event_bus` for unified infrastructure interaction monitoring.
*   **Causal Chain Attribution**: Implemented the `CausalChain` and `DiagnosticResult` models to distinguish between root-cause triggers (e.g., Logical Loop) and terminal symptoms (e.g., Infra Timeout).
*   **Enterprise Extension Support**: Re-categorized high-fidelity analyzers (Strategic Loops, Telemetry Gradients) as plugin-based examples, enabling users to inject advanced diagnostics via the `on_diagnose_failure` hook.
*   **State Parity Enforcement**: Introduced native support for the `initial_state` root property in AES v1.4, enabling deterministic seeding of the `SharedStateRegistry` to ensure 1:1 alignment between agent context and physical environment.
*   **Singleton Process Guard**: Hardened the PID-based lock management (`server.pid`) with active `psutil` stale process remediation, ensuring stable industrial orchestration and preventing port-5000 collisions across concurrent execution windows.
*   **Documentation & Test Sync**: Extensively updated both modern (Starlight) and legacy documentation to reflect the Core/Enterprise structural split and "The Scholar" persona rebranding.

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
