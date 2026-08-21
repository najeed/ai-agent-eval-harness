<!-- README.md (root of the project) -->

# 🛡️ AgentV, The Verification OS for Enterprise AI Agents

[![CI](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Works with AgentV](https://raw.githubusercontent.com/najeed/ai-agent-eval-harness/main/docs/public/assets/badges/works-with-agentv.svg)](https://github.com/najeed/ai-agent-eval-harness)


## The Reliability Gap: Why AgentV Exists

**88% of enterprise AI agents fail to reach production.** Not because the model is wrong. Because no one verified that the agent actually did the right thing.

AgentV sits inside the execution loop and verifies state parity, policy adherence, and business outcomes before your agent earns the right to act. Cryptographically signed traces (Ed25519), deterministic policy verification, CI/CD hard gating, NIST AI-100-1 aligned, and built for regulated industries.

*[5,000+ OOTB scenarios] • [50+ verticals] • [Apache 2.0] • [AgentV Control Plane available]*

## Architecture Overview

```mermaid
graph TD
    classDef agent fill:#f9f9f9,stroke:#333,stroke-width:2px;
    classDef os fill:#1B3B5F,stroke:#fff,stroke-width:2px,color:#fff;
    classDef pass fill:#00d26a,stroke:#333,stroke-width:2px,color:#000;
    classDef fail fill:#ff4b4b,stroke:#333,stroke-width:2px,color:#fff;

    Agent["🤖 Autonomous Agent"]:::agent
    
    subgraph "AgentV Verification OS"
        Sim["🌍 World Shims (Isolated State)"]:::os
        Tel["🧬 Behavioral DNA (Telemetry)"]:::os
        Vault["🔒 Ed25519 Trace Vault"]:::os
        Judge["⚖️ Industrial Policy Judges"]:::os
    end
    
    Pass["🟢 Verified (Cleared for Prod)"]:::pass
    Fail["🔴 Hard Gated (Violation)"]:::fail

    Agent -- "Proposes Action/Tool" --> Sim
    Sim -- "Intercepts State Delta" --> Tel
    Tel -- "Hashes Trace Evidence" --> Vault
    Tel -- "Evaluates Adherence" --> Judge
    Judge -- "100% Policy Parity" --> Pass
    Judge -- "Anomalous Behavior" --> Fail
```


| Attribute | Specification |
| :--- | :--- |
| **License** | Apache License 2.0 |
| **Status** | 🟢 Production-Ready (NIST AI-100-1 Aligned) |
| **Version** | v2.0.0 (August 2026 Release) |
| **Trust Model** | [Behavioral DNA & VC v3.0.0](docs/src/content/docs/spec/trust_v3.md) |
| **Architecture** | [Identity-Centric Core](docs/src/content/docs/builder/architecture.md) |
| **Quick Links** | [Quickstart](#zero-key-quickstart-get-running-now) • [AES v1.4 Spec](docs/src/content/docs/spec/aes_schema.md) • [Security](#security-and-governance-audit-ready) • [Editions](#licensing-and-editions) |


### The DNA of Agentic Reliability
- 🌍 **Environmental DNA**: Immutable snapshots of the execution environment—registry state, tool versions, and resource availability to ensure deterministic state parity.
- 🧬 **Behavioral DNA**: High-granularity telemetry (Phase → Action → Step) mapping the agent's decision-making process for precise policy adjudication and drift analysis.
- 🛡️ **Forensic DNA**: Cryptographic anchoring of the entire execution trace using Ed25519 signatures and SHA3-256 hashes, ensuring non-repudiable WORM logs for regulatory compliance.

## Table of Contents
- [What's New in the August 2026 GA Release (v2.0.0)](#whats-new-in-the-august-2026-ga-release-v200)
- [Mission](#mission)
- [Getting Started](#getting-started)
    - [Prerequisites](#prerequisites)
    - [Zero-Key Quickstart](#zero-key-quickstart-get-running-now)
    - [Manual Evaluation](#manual-evaluation-running-the-sample-agent)
- [At a Glance](#at-a-glance)
- [Integrated Visual Suite (Native GUI)](#integrated-visual-suite-native-gui)
- [Security and Governance](#security-and-governance-audit-ready)
- [Troubleshooting](#troubleshooting)
- [How to Contribute](#how-to-contribute)
- [Licensing and Editions](#licensing-and-editions)

## TL;DR: Impact in 60s
Get from zero to evaluated in seconds:
```bash
pip install -e .
agentv quickstart
```
*   **Result**: Launches mock agent, executes a telecom scenario, and builds a report.
*   **Next Step**: `agentv console` for the visual dashboard.


## Mission

Autonomous software must be provably trustworthy before it earns the right to act. AgentV is the open infrastructure that provides the evidence, not just whether your agent said the right thing, but whether it did the right thing, changed the right state, and followed the right policy.

## 🎓 Master the Art of Industrial Verification

Embark on a **4-Phase, 18-Milestone Hands-on Curriculum** designed to take you from foundational agent discovery through zero-trust production governance concepts. This is a learn-by-doing short-story based roadmap for anyone building reliable agentic systems.

| Phase | Path to Mastery | Milestones |
| :--- | :--- | :--- |
| 🟢 **Foundations** | Discovery, Native Adapters, and Sandboxing. | [Start Here](./walkthroughs/Phase%201%20-%20Foundations%20-%20Beginner) |
| 🟡 **Scale** | Batch Evaluation, Pack Management, and Mutation. | [Go Intermediate](./walkthroughs/Phase%202%20-%20Scale%20%26%20Robustness%20-%20Intermediate) |
| 🔴 **Intelligence** | Auto-Translation, Multi-Agent, and DAG Loops. | [Go Advanced](./walkthroughs/Phase%203%20-%20Intelligence%20%26%20Complexity%20-%20Advanced) |
| 🟣 **Governance** | Trace Replay, IJA Consensus, and HITL Overrides. | [Become Expert](./walkthroughs/Phase%204%20-%20Production%20%26%20Governance%20-%20Expert) |

👉 **[Launch the Master Syllabus](./walkthroughs/README.md)** to begin your journey.

## Getting Started

### Prerequisites

-   **Python 3.12+**
-   **pip**

> [!IMPORTANT]
> ### Zero-Key Quickstart (Get Running Now)
> The fastest way to see the harness in action - **no API keys or LLM setup required**:
>
> ```bash
> # 1. Clone the repository
> git clone https://github.com/najeed/ai-agent-eval-harness.git
> cd ai-agent-eval-harness
>
> # 2. Set up a virtual environment (Recommended)
> python -m venv venv
> venv\Scripts\activate  # On Windows
> source venv/bin/activate  # On macOS/Linux
>
> # 3. Install the package in editable mode
> pip install -e .
>
> # 4. Run the Deterministic Quickstart (CLI)
> agentv quickstart
> ```
>
> **What it does:** Spawns a deterministic in-process mock agent, executes a telecom troubleshooting evaluation, and generates a rich HTML report in `reports/`. 100% offline-ready.

> [!TIP]
> **Prefer a visual experience?** After running the quickstart, launch the **Integrated Visual Suite** to replay the trace interactively: `agentv console`. This includes the **Visual AES Builder** for zero-code scenario design. See the [Developer Guide](docs/src/content/docs/builder/developer-guide.md) for details.


## Harness Structure
The harness is organized into the following key components:

-   `/agentv_runtime`: Public Runtime Contracts & Neutral Architecture Seam (`interfaces`, `reference`, `session_components`).
-   `/dataproc_engine`: High-fidelity industrial data extraction engine (7 Sectors, Gold Standards).
-   `/industries`: Evaluation assets (5,000+ starter scenarios) categorized by 50+ industries.
-   `/eval_runner`: Modular Core Engine (Multi-turn loop, Sandbox, Metrics, Simulators, Mutator).
-   `/eval_runner/console`: Flask-based REST API for the Integrated Visual Suite.
-   `/ui/visual-debugger`: Premium React-based Visual Debugger & Dashboard.
-   `/examples`: Sample drift traces and triage scenarios for rapid onboarding.
-   `/reports`: Generated artifacts (JSONL, trajectories, HTML heatmaps).
-   `/runs`: Local execution history (Flight Recorder logs).
-   `/spec/aes`: **Agent Eval Specification (Foundational)** - Benchmark standard v1.4.
-   `/docs`: Deep-dive guides, architecture, and API specifications.
-   `/tests`: Comprehensive test suite (Unit, Integration, Golden, Red-Teaming).
-   `/sample_agent`: Reference implementation for benchmark testing.

- **NIST AI-100-1 Alignment**: Core verification logic developed following **NIST AI RMF principles**, featuring the **Weighted Severity Model (WSM)** for multi-dimensional scoring and forensic **Environmental DNA** snapshots.
- **State Parity Verification**: NIST-aligned mechanism ensuring cryptographic alignment between the agent's internal state and the physical environment (via `initial_state`).
- **Regulatory Safety Floor**: Prevents "safety-washing" by capping aggregate scores at **0.49 (Fail)** if foundational Safety or Security dimensions are compromised.
- **Behavioral DNA Telemetry**: High-granularity event bus (4-level: PHASE, SUBTASK, ACTION, STEP) providing a precise "genetic" map of agent decision-making.
- **Verification Certificate (VC) v3.0.0**: Traces are signed via the **Identity Registry** (Ed25519) and backed by a **Forensic Evidence Ledger** that hashes sidecar artifacts to ensure end-to-end provenance.

### What's New in the August 2026 GA Release (v2.0.0)

The **v2.0.0 August 2026 GA Release** formalizes strict Semantic Versioning guarantees across the public API surface area, establishes the neutral architectural seam between the AgentV OS Runtime and downstream control planes, introduces the primary Visual Console canonical mount, and provides an industrial automated contract verification suite:

- 🖥️ **Primary Visual Console Mount**: The modern React-based Visual Console (`ui/visual-console`) is now the canonical primary console mounted at `/`, `/scenarios`, `/reports`, `/editor`, `/debugger`, `/runner`, and `/trust`, with `/v2` preserved strictly as a backward-compatible route.
- 🔒 **Formal SemVer 2.0.0 Commitment**: Strict Semantic Versioning guarantee across all public contracts and extension ABCs, backed by a mandatory 1-minor-version deprecation lifecycle and published [SemVer Policy Documentation](docs/src/content/docs/auditor/semver-policy.md).
- 📜 **Multi-Tenant ExecutionManifest Contract**: Defined immutable, frozen [`ExecutionManifest`](agentv_runtime/manifest.py) contract bound to `tenant_id` and `workspace_id`, shared across UI preflight, `/v1/evaluate`, backend execution, and cryptographic certificate sealing, hashed via deterministic SHA3-256 canonical JSON serialization.
- 🛡️ **Zero-Trust Enterprise Identity & RBAC**: GUI role derivation strictly driven by server-authoritative session claims (`GET /api/auth/me`), audience-bound delegation tokens (`aud="agentv-plugin"`), dynamic secret resolution, and an isolated developer persona simulator.
- 🎯 **Fail-Closed Execution Readiness & Server-Authoritative Lifecycle**: Server-authoritative scenario state transitions (`POST /api/scenarios/<id>/transition`) enforcing `Draft` → `Validated` → `Ready` → `Deprecated`, with fail-closed preflight diagnostic probes (`POST /api/scenarios/readiness`) verifying schema integrity, agent endpoint reachability, and cryptographic sealers.
- 📊 **Two-Tier Status Model & Decision-First Reports**: Strict separation between process execution status (`RUNNING`, `EXECUTION_COMPLETED`, `EXECUTION_FAILED`, `STALLED`) and verified business decisions (`VERIFIED`, `NOT_VERIFIED`, `POLICY_BREACH`, `UNVERIFIED`), prioritizing verified decision cards in console drawers.
- 🔐 **Zero-Trust Sandboxed Micro-Frontend Protocol**: Dynamic enterprise extensions mount through sandboxed execution environments with byte-level Subresource Integrity (`SHA-384`) verification via WebCrypto `crypto.subtle.digest` and strict origin allowlisting.
- ⏱️ **Run-Scoped Visual Debugger Store**: Ephemeral and historical timeline state strictly partitioned per `(tenant_id, workspace_id, run_id)` with thread-safe locking and durable trace fallback.
- 📦 **Durable Evidence & Deterministic Batch Binding**: Long-running conductor jobs persist state to `results/jobs/{job_id}.json` and output deterministically to `results/batch_{job_id}` without filesystem mtime scans, backed by auditable evidence bundle downloads.
- 🔌 **Active Runtime Extension Interface Wiring**: All 6 public Extension Families under `agentv_runtime.interfaces` (`ExecutionBackend`, `CheckpointStore`, `SigningBackend`, `ArtifactStore`, `PolicyEvaluator`, and `AuthorizationBackend`) and storage interfaces (`CatalogStore`, `RunStore`, `LeaderboardStore`) are actively invoked across runtime execution paths with real caller invocations and zero bypasses.
- ⚛️ **Hybrid Post-Quantum Cryptographic (PQC) Signing**: First-class quantum-resistant non-repudiation via `PQCSigningBackend` (NIST FIPS 204 ML-DSA-65) and privacy-preserving Zero-Exposure Signing (ZES) over SHAKE-256 local digests.
- 🛑 **Fail-Closed Cryptographic Enforcement**: Strict fail-closed execution (`RuntimeError`) when signing is mandatory (`EVAL_REQUIRE_SIGNING=true` or `AUDIT_LEVEL >= 2`) and signing keys are absent.
- 💾 **Durable HITL Checkpoint Persistence**: Automatic state snapshotting via `SessionApprovalManager` and `SessionCheckpointManager` prior to Human-in-the-Loop approval wait loops with full execution resumption.
- ⏯️ **Shared Execution Lifecycle**: Thread-safe `InProcessExecutionBackend` singleton supporting background execution, real-time status polling, cancellation token propagation, and checkpoint resumption over REST (`POST /v1/runs/<run_id>/cancel`, `POST /v1/runs/<run_id>/resume`).
- 🔒 **Centralized Jail Safety (`SafeRunPathResolver`)**: Strict path isolation across `ArtifactStore`, `RunStore`, and `CatalogStore`, eliminating directory traversal vulnerability classes.
- 🛠️ **OSS Reference Implementations**: Complete production reference implementations for all extension and storage families in `eval_runner/reference/` and re-exported via `agentv_runtime/reference.py`.
- 🏷️ **Subsystem Contract Version Dunders**: Authoritative version identifiers published in `eval_runner` and `agentv_runtime`.
- 🧪 **Automated Contract Test Suite (`tests/contracts/`)**: Continuous zero-regression contract tests verifying interface wiring, adapter contracts, AES v1.4 scenario structures, deterministic SHA3-256 config hashes, 4-method execution lifecycle, plugin discovery hooks, and VC v3.0.0 certificate chains.
- ⚙️ **Resolved Runtime Config & Authoritative Dependency Injection**: Schema-validated runtime configuration model with deterministic SHA3-256 hash digest (`config_hash`) for Processing Integrity evidence, hierarchical config-mesh resolution, and explicit dependency injection through `DefaultRunner` $\rightarrow$ `SessionManager` $\rightarrow$ Subsystem Components.
- 🔒 **Hard Artifact Sealing & Vault Immutability**: `ArtifactStore` enforces strict immutable state transitions (`seal()`, `is_sealed()`) that reject post-seal mutations, appends, and deletes with `PermissionError`.
- 🔐 **Hardened Authorization & Secret Masking**: `SimpleAPIKeyAuthBackend` eliminates plaintext key exposure in initialization logs and masks key tokens in `list_keys(mask=True)` and structured `list_principals()`.
- 🧩 **Modular Subsystem Decomposition**: Monolithic session orchestration decomposed into dedicated, independently testable subsystem managers: `TurnStateManager`, `ToolExecutionCoordinator`, `SessionCheckpointManager`, and `SessionApprovalManager`.

## 📂 The Global Scenario Corpus

The harness now ships with a validated corpus of **5,000+ scenarios** designed to test agents across various industry workflows and edge cases:

### 🏛️ Industry-Specific (4,000+ Scenarios)
Comprehensive coverage for **50+ verticals** including:
- **Finance & Banking**: Loan processing, fraud detection, and regulatory audits.
- **Healthcare**: PII handling, insurance reconciliation, and diagnostic workflows.
- **Telecom & Energy**: Network troubleshooting, grid optimization, and billing.

### 🧠 Advanced Categories (1,000+ Scenarios)
- **Cross-Industry Negotiation**: Scenarios where agents must bridge data and policy gaps between two distinct verticals (e.g., Legal & Healthcare).
- **Ethical & Safety Guardrails**: Hardened tests for PII leakage, prompt injection, and bias.
- **Interactive Complexity**: Multi-turn flows involving conflicting human-in-the-loop (HITL) requirements.
- **Simulations**: High-fidelity sector labs (e.g., Bank, EHR/HL7, CRM) for testing agents in realistic, isolated environments.

*All scenarios are 100% compliant with the [AES v1.4 Specification](docs/src/content/docs/spec/aes_schema.md).*


### Manual Evaluation (Running the Sample Agent)

1.  **Start your Agent**: The framework includes a reference agent for testing.
    ```bash
    python sample_agent/agent_app.py
    ```
2.  **Set Endpoint**: Point the harness to your agent's webhook.
    ```bash
    set AGENT_API_URL=http://localhost:5001/execute_task   # Windows
    export AGENT_API_URL=http://localhost:5001/execute_task # Mac/Linux
    ```
3.  **Run Evaluation**: 
    ```bash
    # Standard HTTP (default)
    # Using Scenario ID alias (Cataloged)
    agentv evaluate --path loan_risk

    # Using project-relative path (Ad-hoc)
    agentv evaluate --path industries/telecom

    # Local Subprocess (stdin/stdout)
    agentv evaluate --path my_scenarios/ --protocol local --agent-cmd "python my_agent.py"

    # Socket (TCP/Unix)
    agentv evaluate --path tests/scenarios --protocol socket --agent-socket "localhost:9000"
    ```

> [!NOTE]
> **Path Decoupling**: The harness now supports ad-hoc evaluations anywhere on your filesystem. Metadata like `industry` is inferred from the file content or folder structure, defaulting to `local` and `unclassified` for external files.

---

## Agent Communication Protocols

The harness supports multiple ways to talk to your agent. Use the `--protocol` flag to select the adapter and `--agent` (or specialized flags) to specify the endpoint.

| Protocol | Description | Configuration Flag | Env Variable |
| :--- | :--- | :--- | :--- |
| **HTTP** | Standard REST API (POST) | `--protocol http` (default) | `AGENT_API_URL` |
| **SSE** | Server-Sent Events | `--protocol sse` | *(None)* |
| **Local** | Local process via stdin/stdout | `--protocol local` or `--agent-cmd` | `AGENT_LOCAL_CMD` |
| **Socket** | TCP or Unix Domain Socket | `--protocol socket` or `--agent-socket` | `AGENT_SOCKET_ADDR` |
| **OpenAPI** | OpenAPI spec (REST) | `--protocol openapi` | *(None)* |

---

## At a Glance

- **Evaluation Specification (AES)**: Standardized YAML/Markdown benchmarks for agents.
- **20-Shim Enterprise Suite**: Environment simulators for **Git, API, Database, Knowledge Base, Support Desk, Social Media, Vector DB, CI/CD, IoT, Security**, and more (AgentV Control Plane supports high-fidelity versions).
- **Schema-Driven Core Registry**: Decoupled environmental state management using declarative manifests (`shim_resources.json`) with **Async Simulation Hardening** for non-blocking non-linear evaluations.
- **PBAC & Operational Governance**: Granular **Permission-Based Access Control** (v1.2.3) and **Operational Throttling** (`EVAL_TURN_THROTTLE`) for regulated enterprise environments.
- **Zero-Touch Hot-Swap Architecture**: Dynamically register and swap simulators via plugins without core code modifications.
- **Benchmark Ecosystem**: Native loaders for GAIA (HuggingFace Integration) and AssistantBench. Supports benchmark URI schemes (e.g., `gaia://2023`, `assistantbench://v1`) for zero-config execution.
- **Native Framework Adapters**: Full industrial-grade support for **LangChain**, **LangGraph**, **Microsoft AutoGen** (via `ag2://`), and **CrewAI** via a dynamic plugin-discovery system.
- **High-Fidelity Industry Metrics**: Modular, pluggable evaluators for Defense (ROE, C2, Intelligence Fusion), Healthcare, and Finance. Features high-precision numerical extraction and domain-specific LLM rubrics.
- **Tool Sandbox**: Governance-controlled execution with full VFS-aware state parity verification and TOCTOU barrier race protection.
- **AST Mutation Testing Sentinel**: Surgical AST mutation testing pipeline enforcing >=90% kill rate (100% achieved) across verification modules.
- **Integrated Visual Suite (`/v2`)**: Unified React dashboard featuring dynamic navigation manifest ingestion (`GET /api/nav`), runtime micro-frontend module federation, live trace replay, and visual debugging.
- **Stratified Failure Taxonomy**: Formal, Enum-based failure registry (NIST-aligned) for precise, audit-grade root-cause diagnostics.
- **Semantic Bridge**: Ingest production traces (`import-drift`) and analyze failures (`triage`).
- **Judge Guarding**: Model-based scoring with support for OpenAI, Gemini, Claude, and Ollama.

#### Advanced CLI Suite
- **`list`**: Faceted search filtering across 5,000+ industry scenarios via `--search`.
- **`lint`**: Automated quality scoring and AES compliance verification via `--path`.
- **`install <pack>`**: Rapid deployment of curated, industry-specific scenario bundles (e.g., `telecom-pack`, `rag-agent-pack`).
- **`analyze <url>`**: Proactive agent repo scanning; auto-generates AES stubs by identifying tools and endpoints.
- **`ci generate`**: One-click scaffolding of GitHub Actions workflows for evaluation-on-PR.
- **`failures search`**: Intelligence-driven retrieval of edge cases from the global failure corpus.
- **`explain`**: AI-powered trace diagnostics (loops, timeouts, PII leaks) via `--run-id <id>`.
- **`certify`**: Generate a non-repudiable Verification Certificate (VC) for a specific run trace using `--run-id`.
- **`verify`**: Verify the cryptographic integrity of a run trace using autonomous artifact resolution via `--run-id`.
- **`gate`**: "Hard Gating" tool for CI/CD pipelines to enforce signature and hash matches via `--run-id`.
- **`auto-translate`**: Leverage local LLMs (via Ollama) to convert raw documents into executable AES scenarios.
- **`aes add-standard`**: Expand the global industrial registry with new standard definitions (ID, Name, Industry, Description).
- **`init --standard <id>`**: Rapidly scaffold a dedicated, industry-compliant evaluation environment for a specific standard (e.g., `init --standard ISO_20022`).

and more (check [CLI Reference](docs/src/content/docs/evaluator/cli-reference.md) for complete list) ...


#### Premium UX Tools
- **Scenario Editor**: A visual interface for constructing real-world AES logic; saves production-ready JSON directly to the catalog.
- **VS Code Extension**: Run evaluations and visualize timelines directly within your IDE.
- **Visual Debugger**: Real-time trajectory playback with interactive state inspection (Live Engine Hook).

---

The harness is built on a decoupled, event-driven architecture that allows custom integrations to be hot-swapped without core modifications.

- **EventEmitter Bus**: Passive observation of every turn, tool call, and state change.
- **🧩 Pluggable Judge Layer**: Configurable model-based scoring with support for OpenAI, Gemini, Claude, and Ollama.
- **🏥 High-Fidelity Metrics Framework**: Decoupled, category-based evaluators (Accuracy, Planning, Defense, Technical) with extensible registration.
- **Industry-Standard Rubrics**: Specialized evaluators for Clinical Safety, Fiduciary Accuracy, Strategic Planning, and Causal Inference.
- **Native HITL Support**: built-in pausing for human intervention via the `human` adapter.
- **Advanced Discovery**: Plugin-driven registry for third-party agent adapters (LangGraph, CrewAI, AutoGen, Grok).
- **Pluggable World Shims**: Register custom environment simulators through the `on_register_simulators` hook.
- **Pluggable Console & GUI Extensions**: Inject custom React views, dynamic navigation manifests, and REST endpoints via the `on_register_console_routes` hook.

### 🛠️ dataproc-engine: Industrial Extraction Core
The repository also features a standalone extraction engine designed for high-fidelity data acquisition:
- **Sector Coverage**: Finance, Healthcare, Energy, Telecom, Ecommerce, Agriculture, and Transportation.
- **Zero-Mock Integrity**: Automated fallback to high-fidelity simulations when live APIs are unavailable, maintaining 100% data availability.

Beyond the advanced suite, the harness provides a robust toolkit for professional evaluation:
- **`doctor`**: Environment health checker.
- **`report`**: Rich HTML reporting with interactive Mermaid trajectories via `--path`.
- **`record` & `playground`**: Interaction capture and REPL experimentation for rapid prototyping.
- **`spec-to-eval`**: Convert Markdown PRDs/Specs into executable JSON scenarios. Supports `--fill-defaults` to rapidly generate lint-compliant stubs.
- **`scenario generate`**: Interactive scaffolding for manual test authoring.
- **`mutate`**: Adversarial scenario generator (typos, injections, ambiguity).
- **`import-drift`**: Convert production logs into regression test cases.

## Integrated Visual Suite (Native GUI)

The harness includes a unified **React-powered SPA** (`/v2`) that simplifies management of scenarios, runs, and visual debugging across all industries.

**Key Feature Hubs:**
- **Dynamic Navigation & Micro-Frontends**: Dynamic manifest ingestion (`GET /api/nav`) and zero-recompilation runtime module federation via standard ESM `import()`.
- **Scenario Explorer**: Browse the catalog with faceted filters, global search, and real-time **Quality Badges** (Lint scores).
- **Visual AES Builder**: Construction of complex agentic evaluation sequences using a drag-and-drop node logic—outputs production-ready JSON.
- **Reports & Traces Hub**: Historical execution timeline with detailed analysis and instant "View Report" navigation.
- **Interactive Visual Debugger**: Real-time trajectory playback, state inspection, and trace export (JSON) for regression testing.
- **Documentation Hub**: Categorized access to all Markdown guides, architectural diagrams, and API references.
- **Sidebar Badging & Role Gating**: Support for status badges (`LIVE`, `APM`, `CUSTOM`), enterprise tier chips, and granular RBAC role gating.

**Quick Launch:**
```bash
agentv console
```
*Access via browser at `http://localhost:5000`. The console features an adaptive, premium dark-mode UI with high-density data visualizations.*

### Running Tests

```bash
python -m pytest
```

### Centralized Configuration

All configurable parameters are centralized in `eval_runner/config.py`. You can override any setting via environment variables.

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent entry point URL (HTTP) |
| `EVAL_MAX_TURNS` | `10` | Max conversation turns per task |
| `MAX_ENGINE_ATTEMPTS` | `50` | Security cap on evaluation attempts |
| `JUDGE_PROVIDER` | `ollama` | LLM Judge provider (`openai`, `anthropic`, `gemini`, `ollama`, `grok`) |
| `JUDGE_MODEL` | *(None)* | Specific model for the judge |
| `LUNA_JUDGE_TEMPERATURE`| `0.0` | Temperature for judge generation |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama host URL |
| `OLLAMA_MODEL` | `llama4` | Default Ollama model |
| `OPENAI_API_KEY` | *(None)* | API key for OpenAI provider |
| `ANTHROPIC_API_KEY`| *(None)* | API key for Anthropic/Claude provider |
| `GOOGLE_API_KEY` | *(None)* | API key for Google/Gemini provider |
| `XAI_API_KEY` | *(None)* | API key for xAI/Grok provider |
| `DASHBOARD_API_KEY`| *(None)* | Mandatory key for Visual Debugger & REST API security |
| `EVAL_TURN_THROTTLE`| `0.0` | Artificial delay (seconds) between agent turns |
| `DEFAULT_ADAPTER_TIMEOUT`| `30` | Network timeout for agent adapters |
| `PLUGIN_TIMEOUT` | `5.0` | Execution timeout for plugin hooks |
| `REPORTS_DIR` | `reports` | Base directory for generated reports |

... and more.

### Security and Governance (Audit-Ready)
The platform is built with a **Secure-by-Design** philosophy, complying with enterprise-grade audit standards.

- **PII/Secret Redaction**: Automatic, recursive scanning and redaction of JWTs, AWS keys, and PII from all event logs.
- **Secure Handoff Architecture**: JWT-based authentication for between the core console and enterprise plugins.
- **Tool Sandboxing**: Path traversal protection and shell-character neutralization for all tool executions.
- **WORM Logs**: Write-Once-Read-Many immutable flight recorder traces (`run.jsonl`).
- **Audit Controls**: Defense-in-depth security controls (DoS caps, Fork Bomb prevention, RCE guards, and jail isolation). See the [Security Guide](docs/src/content/docs/auditor/security.md) for generation and configuration instructions.
- **Mandatory Authentication**: Protection of all console and bridge routes via the `DASHBOARD_API_KEY`.

### 🗄️ Forensic Storage & Vaulting
AgentV employs a **Strict Industrial Vault** methodology to protect run integrity:
- **Individual Vaults**: By default, each execution is isolated in its own directory (`runs/<run_id>/run.jsonl`).
- **Master Log**: A consolidated flight recorder at `runs/run.jsonl` tracks all system turns for aggregate analysis.
- **Rotation**: The built-in rotation mechanism manages entire Vault Directories, purging historical subdirectories to maintain storage efficiency while preserving the most recent forensic artifacts. It is recommended to periodically clean up this directory via `agentv cleanup-runs`.

### Troubleshooting

- **`ConnectionRefusedError`**: The harness cannot reach the agent. Ensure `AGENT_API_URL` is set correctly and the agent API is running.
- **`PluginTimeoutError`**: A registered plugin took too long to execute a hook. Check your plugin logic or increase the timeout.
- **`Invalid JSON Error (LLM)`**: The `auto-translate` command expects strict JSON. Ensure your local Ollama model (e.g., `llama4`) is running and capable of JSON mode.
- **`docker: command not found`**: You need to install Docker if you intend to use Lab Mode.

---

## 🚀 Advanced Setup (Docker & Lab Mode)

For researchers needing full isolation or enterprise-grade local dashboards, we provide a containerized stack.

### Prerequisites
- **Docker & Docker Compose**:
    - **Windows/Mac**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
    - **Linux**: Install [Docker Engine](https://docs.docker.com/engine/install/) and [Docker Compose](https://docs.docker.com/compose/install/).

### Launching the Stack
```bash
docker compose up --build
```
This orchestrates the Flask backend, the React frontend, and the execution engine in a secure, isolated network.

### Running Lab Mode without Docker
If you cannot install Docker, run these 2 commands in separate terminals:
1. `python sample_agent/agent_app.py`
2. `agentv console`

## How to Contribute

This is a community-driven project, and we welcome contributions! Please see our [CONTRIBUTING.md](CONTRIBUTING.md) file for detailed guidelines on how to add new industries, scenarios, or improve the engine.

Here are ways to get involved:

### 🌟 Quick Contributions
- ⭐ Star this repository
- 🐛 [Report bugs](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=bug_report.md)
- 💡 [Suggest features](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=feature_request.md)
- 📖 [Improve documentation](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=documentation.md)

### 🔨 Code Contributions
- 🆕 [Good first issues](https://github.com/najeed/ai-agent-eval-harness/labels/good%20first%20issue)
- 🧪 Add test scenarios
- ⚖️ **Zero-CLA**: We use the DCO (Developer Certificate of Origin). Just `git commit -s`.
- 🏭 [Contribute new industries](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=industry_request.md)
### Contributors
Thanks to all our contributors! 🙌

<a href="https://github.com/najeed/ai-agent-eval-harness/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=najeed/ai-agent-eval-harness" />
</a>

## Licensing and Editions

This project follows an **Open Core** model. The open-source AgentV OS Runtime capabilities provide a robust verification foundation, while the AgentV Control Plane delivers the necessary security, governance, and audit-grade intelligence required for regulated deployments.

| Feature Module | AgentV OS Runtime (OSS) | AgentV Control Plane |
| :--- | :--- | :--- |
| **Core Architecture** | ✅ Eval Engine, Hooks, JSON Schemas | ✅ Enterprise Service Bus Integration |
| **Industry Benchmark Set** | ✅ 5,000+ Starter Scenarios | ✅ Prioritized Scenario Updates |
| **Reliability Metrics** | ✅ `pass@k` multi-attempt scoring | ✅ Persistent Leaderboards & Consensus |
| **Scenario Mutations** | 🔶 Basic (Typos & Ambiguity) | ✅ Adversarial Fuzzing & Prompt Injections |
| **Execution Security** | 🔶 Basic Path/Shell Gating | ✅ Context Payload Caps & Overflow Guards |
| **Privacy Protections** | ❌ No | ✅ Automatic PII Scanning & Redaction |
| **Simulation** | 🔶 Real API required | ✅ High-Fidelity Labs (Bank, EHR/HL7, CRM) |
| **Compliance Suites** | ❌ No | ✅ Production-Ready (HIPAA, FINRA, GDPR, PCI) |
| **Observability** | 🔶 Terminal output | ✅ OTEL Drift Gauges & Dashboard Feed |
| **Defensibility Governance**| ❌ No | ✅ WORM Audit Logs & Chained Integrity |
| **Integrity Checks** | ✅ Ed25519 Trace Validation | ✅ AES Scenario Merkle Sync (Root Verify) |
| **Visual Debugger & GUI** | ✅ Local React Native App | ✅ Enterprise Dashboard & Secure Handoff |
| **Reproduction Workflow** | 🔶 JSONL Only | ✅ Interactive Flight Recorder & Jupyter Repro |
| **Parallel Engine** | 🔶 Sequential only | ✅ Ray/Local JobQueue Distributed Runs |
| **Interactive Triage** | 🔶 Heuristic only | ✅ Multi-user Sync & Human Annotation |
| **Advanced Sandbox** | 🔶 Path/Shell Gating | ✅ Hardened Docker Isolation & Red-Team Probes |
| **Auth & Governance** | 🔶 Basic Auth | ✅ OIDC SSO, SCIM provisioning, PBAC, Managed Leaderboards |

**Legend:** ✅ Full Capability • 🔶 Basic/OSS Only • ❌ Enterprise Only

### 🛡️ Add the Badge to Your Agent

Showcase your agent's rigorous reliability by adding the official **Works with AgentV** badge to your repository to show that it has been evaluated by the AgentV framework.

#### Option 1: Using img.shields.io
You can use the Shields.io service to generate a consistent badge for your project:

```markdown
[![Works with AgentV](https://img.shields.io/badge/Works%20with-AgentV-2c62c7)](https://github.com/najeed/ai-agent-eval-harness)
```

#### Option 2: Using GitHub Asset
Alternatively, link directly to our high-fidelity SVG asset:

```markdown
[![Works with AgentV](https://raw.githubusercontent.com/najeed/ai-agent-eval-harness/main/docs/public/assets/badges/works-with-agentv.svg)](https://github.com/najeed/ai-agent-eval-harness)
```

---

Ready for production-grade verification? The AgentV Control Plane delivers WORM audit logs, OIDC SSO, PBAC, HIPAA/FINRA/GDPR compliance packs, and Docker-sandboxed isolation, everything regulated industries need before autonomous agents earn the right to act.

👉 Book a 30-minute call: [AgentVOS.ai](https://agentvos.ai)

### License
The core of this project is licensed under the **Apache License 2.0**. 
See the [LICENSE](LICENSE) file for details.
