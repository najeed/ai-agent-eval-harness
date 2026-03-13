<!-- README.md (root of the project) -->

# 🤖 AI Agent Evaluation Harness

[![CI](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Security Audit](https://img.shields.io/badge/Security-Audit--Compliant-green.svg)](docs/architecture.md#security-guardrails)
[![Documentation](https://img.shields.io/badge/Docs-Comprehensive-brightgreen.svg)](docs/guides/help/00_COMPREHENSIVE_GUIDE.md)

**AI Agent Evaluation Harness** is the enterprise-grade reliability framework for AI agents. It bridges the "Agentic Reliability Gap" through rigorous evaluation, deep-trace replay debugging, and industry-standard benchmark datasets.

| Attribute | Specification |
| :--- | :--- |
| **Architect** | [Najeed Ahmed Khan](https://github.com/najeed) |
| **License** | Apache License 2.0 |
| **Status** | Production-Ready Framework |
| **Core Goal** | Eliminating the "Agentic Reliability Gap" |
| **Quick Links** | [Quickstart](#60-second-quickstart-get-running-now) • [Advanced Update](#the-advanced-update-v11) • [Architecture](#zero-touch-core-architecture) • [Security](#security-and-governance-audit-ready) • [Editions](#licensing-and-editions) |

## Table of Contents
- [Mission](#mission)
- [Getting Started](#getting-started)
    - [Prerequisites](#prerequisites)
    - [60-Second Quickstart](#60-second-quickstart-get-running-now)
    - [Manual Evaluation](#manual-evaluation-running-the-sample-agent)
- [At a Glance (v1.0 RC)](#at-a-glance-v10-rc)
- [The Advanced Update (v1.1)](#the-advanced-update-v11)
- [Zero-Touch Core Architecture](#zero-touch-core-architecture)
    - [Advanced Utilities](#advanced-utilities)
- [Web Admin Console (Native GUI)](#web-admin-console-native-gui)
- [Security and Governance](#security-and-governance-audit-ready)
- [Troubleshooting](#troubleshooting)
- [How to Contribute](#how-to-contribute)
- [Licensing and Editions](#licensing-and-editions)

## TL;DR: Impact in 60s
Get from zero to evaluated in seconds:
```bash
pip install -e .
eval-harness quickstart
```
*   **Result**: Launches mock agent, executes a telecom scenario, and builds a report.
*   **Next Step**: `eval-harness console` for the visual dashboard.

## Mission

Our goal is to create a standardized, community-driven benchmark for AI agent performance. By providing a rich set of industry-specific scenarios and a flexible evaluation runner, we aim to help developers, researchers, and businesses measure and improve their agent-based systems.

The harness is organized into the following key components:

-   `/industries`: Evaluation assets (4,600+ scenarios) categorized by 44 industries.
-   `/eval_runner`: Modular Core Engine (Multi-turn loop, Sandbox, Metrics, Simulators, Mutator).
-   `/eval_runner/console`: Flask-based REST API for the **Integrated Visual Suite**.
-   `/ui/visual-debugger`: Premium React-based Visual Debugger & Dashboard.
-   `/admin-console`: [DEPRECATED] Legacy React Native prototype.
-   `/examples`: Sample drift traces and triage scenarios for rapid onboarding.
-   `/reports`: Generated artifacts (JSONL, trajectories, HTML heatmaps).
-   `/runs`: Local execution history (Flight Recorder logs).
-   `/spec/aes`: **Agent Eval Specification (Foundational)** - Benchmark standard.
-   `/schemas`: JSON Schema definitions for cross-platform scenario validation.
-   `/docs`: Deep-dive guides, architecture, and API specifications.
-   `/tests`: Comprehensive test suite (Unit, Integration, and Red-Teaming).
-   `/sample_agent`: Reference implementation for benchmark testing.

## Getting Started

### Prerequisites

-   **Python 3.8+**
-   **pip**
-   **Docker & Docker Compose (optional, for Lab Mode)**:
    -   **Windows/Mac**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
    -   **Linux**: Install [Docker Engine](https://docs.docker.com/engine/install/) and [Docker Compose](https://docs.docker.com/compose/install/).

> [!IMPORTANT]
> ### 60-Second Quickstart (Get Running Now)
> The fastest way to see the harness in action:
>
> ```bash
> # 1. Clone the repository
> git clone https://github.com/najeed/ai-agent-eval-harness.git
> cd ai-agent-eval-harness
>
> # 2. Set up a virtual environment (Recommended)
> python -m venv venv
> venv\Scripts\activate  # On Windows
> # source venv/bin/activate  # On macOS/Linux
>
> # 3. Install the package in editable mode
> pip install -e .
>
> # 4. Run the Quickstart Demo (CLI)
> eval-harness quickstart
> ```
>
> **What it does:** Spawns a mock sample agent, runs a troubleshooting evaluation, and generates a rich legacy HTML report in `reports/`.

> [!TIP]
> **Prefer a visual experience?** After running the quickstart, launch the **Admin Console** to replay the trace interactively: `eval-harness console`.

*(Optional Full Lab Mode):* For the complete dashboard and database experience, you can use `docker compose up --build`. If you don't have Docker, you can run services manually (see [Troubleshooting](#-troubleshooting)).

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
    eval-harness evaluate --path industries/telecom

    # Local Subprocess (stdin/stdout)
    eval-harness evaluate --path industries/telecom --protocol local --agent-cmd "python my_agent.py"

    # Socket (TCP/Unix)
    eval-harness evaluate --path industries/telecom --protocol socket --agent-socket "localhost:9000"
    ```

---

## Agent Communication Protocols

The harness supports multiple ways to talk to your agent, enabling seamless integration with local scripts, legacy binaries, or remote services.

| Protocol | Description | Configuration Flag | Env Variable |
| :--- | :--- | :--- | :--- |
| **HTTP** | Standard REST API (POST) | `(default)` | `AGENT_API_URL` |
| **Local** | Local process via stdin/stdout | `--agent-cmd` | `AGENT_LOCAL_CMD` |
| **Socket** | TCP or Unix Domain Socket | `--agent-socket` | `AGENT_SOCKET_ADDR` |

---

## At a Glance (v1.0 RC)

- **Evaluation Specification (AES)**: Standardized YAML/Markdown benchmarks for agents.
- **Benchmark Ecosystem**: Native loaders and adapters for community benchmarks like GAIA and AssistantBench.
- **Pluggable Architecture**: Extend anything via Python plugins, with out-of-the-box framework adapters for **LangGraph**, **CrewAI**, and **Microsoft AutoGen**.
- **Tool Sandbox**: Governance-controlled execution of real or mock tools.
- **Visual Admin Console**: Integrated React Native (Expo) dashboard for live trace replay and visual debugging.
- **Semantic Bridge & Distribution**: Ingest production traces (`import-drift`), analyze failures (`triage`), and export datasets to HuggingFace (`export`).
- **Research-Grade Orchestration**: Support for `pass@k`, non-linear trajectories (`fork()`), and HITL.
- **Robust Metrics**: 12+ built-in metrics (Tool Correctness, State Parity, Policy Compliance, and LLM-Judged Clarity).
- **Multi-Model LLM Judge (Luna-Judge)**: Advanced scoring via pluggable providers (OpenAI, Gemini, Claude, Ollama, xAI Grok).
- **Centralized Configuration**: All system constants and environment defaults managed via `eval_runner/config.py`.

## The Advanced Update (v1.1)

The latest release introduces a new suite of high-level automation and visual tools designed for 10x developer productivity.

#### Advanced CLI Suite
- **`list`**: Faceted search filtering across 4,600+ industry scenarios.
- **`lint`**: Automated quality scoring and AES compliance verification.
- **`install <pack>`**: Rapid deployment of curated, industry-specific scenario bundles (e.g., `telecom-pack`, `rag-agent-pack`).
- **`analyze <url>`**: Proactive agent repo scanning; auto-generates AES stubs by identifying tools and endpoints.
- **`ci generate`**: One-click scaffolding of GitHub Actions workflows for evaluation-on-PR.
- **`failures search`**: Intelligence-driven retrieval of edge cases from the global failure corpus.
- **`explain <run.jsonl>`**: AI-powered trace diagnostics identifying root causes (loops, timeouts, PII leaks).
- **`auto-translate`**: Leverage local LLMs (via Ollama) to convert raw documents into executable AES scenarios.

#### Premium UX Tools
- **Scenario Editor**: A visual React Native interface for constructing real-world AES logic—saves production-ready JSON directly to the catalog.
- **VS Code Extension**: Run evaluations and visualize timelines directly within your IDE.
- **Visual Debugger**: Real-time trajectory playback with interactive state inspection (Live Engine Hook).

---

## Zero-Touch Core Architecture

The harness is built on a decoupled, event-driven architecture that allows Enterprise integrations to be hot-swapped without core modifications.

- **EventEmitter Bus**: Passive observation of every turn, tool call, and state change.
- **🧩 Pluggable Judge Layer**: Configurable model-based scoring (Luna-Judge) with support for OpenAI, Gemini, Claude, and Ollama.
- **🏥 Industry-Standard Rubrics**: Built-in specialized evaluators for Clinical Safety (Healthcare), Fiduciary Accuracy (Finance), and Policy Adherence (Legal).
- **⚖️ Judge Calibration**: Automated alignment checking between automated judge scores and human ground truth via the `calibrate` command.
- **Interception Hooks**: Plugins can now intercept and block tool calls (`on_tool_request`) or register custom adapters.
- **Native HITL Support**: Built-in support for pausing evaluation for human intervention via the `human` adapter.
- **Non-Linear Trajectories**: Support for branching and forking trajectories (`fork()`) in `SessionManager` for research-grade evaluations.
- **Advanced Discovery**: Plugin-driven registry for third-party agent adapters (LangGraph, CrewAI, AutoGen, Grok) via the `on_discover_adapters` hook.
- **Immutable Contexts**: Ensures plugins cannot introduce side-effects into the core engine state.


### Advanced Utilities
Beyond the advanced suite, the harness provides a robust toolkit for professional evaluation:
- **`doctor`**: Environment health checker.
- **`report`**: Rich HTML reporting with interactive Mermaid trajectories.
- **`record` & `playground`**: Interaction capture and REPL experimentation for rapid prototyping.
- **`spec-to-eval`**: Convert Markdown PRDs/Specs into executable JSON scenarios.
- **`scenario generate`**: Interactive scaffolding for manual test authoring.
- **`mutate`**: Adversarial scenario generator (typos, injections, ambiguity).
- **`import-drift`**: Convert production logs into regression test cases.

## Web Admin Console (Native GUI)

The harness includes a unified **React-powered SPA** Admin Console that simplifies management of scenarios, runs, and visual debugging across all industries.

**Key Feature Hubs:**
- **Scenario Explorer**: Browse the catalog with faceted filters, global search, and real-time **Quality Badges** (Lint scores).
- **Visual AES Builder**: Construction of complex agentic evaluation sequences using a drag-and-drop node logic—outputs production-ready JSON.
- **Reports & Traces Hub**: Historical execution timeline with detailed analysis and instant "View Report" navigation.
- **Interactive Visual Debugger**: Real-time trajectory playback, state inspection, and trace export (JSON) for regression testing.
- **Documentation Hub**: Categorized access to all Markdown guides, architectural diagrams, and API references.

**Quick Launch:**
```bash
eval-harness console
```
*Access via browser at `http://localhost:5000`. The console features an adaptive, premium dark-mode UI with high-density data visualizations.*

### Running Tests

```bash
pytest tests/ -v -p no:plugin_gateway
```

### Centralized Configuration

All configurable parameters are centralized in `eval_runner/config.py`. You can override any setting via environment variables.

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent entry point URL (HTTP) |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `MAX_ENGINE_ATTEMPTS` | `50` | Security cap on evaluation attempts |
| `JUDGE_PROVIDER` | `ollama` | LLM Judge provider (`openai`, `anthropic`, `gemini`, `ollama`, `grok`) |
| `JUDGE_MODEL` | *(None)* | Specific model for the judge |
| `LUNA_JUDGE_TEMPERATURE`| `0.0` | Temperature for judge generation |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama host URL |
| `OLLAMA_MODEL` | `llama3` | Default Ollama model |
| `OPENAI_API_KEY` | *(None)* | API key for OpenAI provider |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for OpenAI-compatible APIs |
| `ANTHROPIC_API_KEY`| *(None)* | API key for Anthropic/Claude provider |
| `GOOGLE_API_KEY` | *(None)* | API key for Google/Gemini provider |
| `XAI_API_KEY` | *(None)* | API key for xAI/Grok provider |
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
- **Audit Points**: 100% compliance with the 8-point Enterprise Security Audit (DoS caps, Fork Bomb prevention, RCE guards).

### Run Trace Warning
All evaluation execution logs are appended to `runs/run.jsonl`. Because this acts as an immutable flight recorder, the file will grow continuously. It is recommended to use the built-in trace rotation or periodically clean up this directory via `eval-harness cleanup-runs --days 7`.

### Troubleshooting

- **`ConnectionRefusedError`**: The harness cannot reach the agent. Ensure `AGENT_API_URL` is set correctly and the agent API is running.
- **`GoException: no routes for location`**: Occurs in the Flutter UI dashboard if the router isn't rebuilt. Re-run `flutter pub run build_runner build`.
- **`PluginTimeoutError`**: A registered plugin took too long to execute a hook. Check your plugin logic or increase the timeout.
- **`Invalid JSON Error (LLM)`**: The `auto-translate` command expects strict JSON. Ensure your local Ollama model (e.g., `llama3`) is running and capable of JSON mode.
- **`docker: command not found`**: You need to install Docker. Follow the [Official Installation Guide](https://docs.docker.com/get-docker/).
- **Running Lab Mode without Docker**:
    If you cannot install Docker, run these 3 commands in separate terminals:
    1. `python sample_agent/agent_app.py`
    2. `eval-harness console`
    3. `streamlit run dashboard/app.py` (requires `pip install streamlit`)

## How to Contribute

This is a community-driven project, and we welcome contributions! Please see our [CONTRIBUTING.md](CONTRIBUTING.md) file for detailed guidelines on how to add new industries, scenarios, or improve the evaluation engine.

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
- 🎯 [Create evaluation scenarios](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=scenario_contribution.md)

### Contributors
Thanks to all our contributors! 🙌

<a href="https://github.com/najeed/ai-agent-eval-harness/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=najeed/ai-agent-eval-harness" />
</a>

## Licensing and Editions

This project follows an **Open Core** model. The open-source capabilities provide a robust evaluation foundation, while the Enterprise Edition delivers the necessary security, governance, and audit-grade intelligence required for regulated deployments.

| Feature Module | Community Edition (OSS) | Enterprise Edition |
| :--- | :--- | :--- |
| **Core Architecture** | ✅ Eval Engine, Hooks, JSON Schemas | ✅ Enterprise Service Bus Integration |
| **Industry Benchmark Set** | ✅ 4,600+ Scenarios | ✅ Prioritized Scenario Updates |
| **Reliability Metrics** | ✅ `pass@k` multi-attempt scoring | ✅ Persistent Leaderboards & Consensus |
| **Scenario Mutations** | 🔶 Basic (Typos & Ambiguity) | ✅ Adversarial Fuzzing & Prompt Injections |
| **Execution Security** | 🔶 Basic Path/Shell Gating | ✅ Tool Sandboxing & Context Payload Caps |
| **Privacy Protections** | ❌ No | ✅ Automatic PII Scanning & Redaction |
| **Simulation** | 🔶 Real API required | ✅ High-Fidelity Labs (Bank, EHR/HL7, CRM) |
| **Compliance Suites** | ❌ No | ✅ Turn-key Packs (HIPAA, FINRA, GDPR, PCI) |
| **Observability** | 🔶 Terminal output | ✅ OTEL Drift Alerts & Jira Auto-Ticketing |
| **Defensibility Governance**| ❌ No | ✅ WORM Audit Logs & Cryptographic Traces|
| **Integrity Checks** | ❌ No | ✅ AES Scenario Merkle Sync |
| **Admin Console & GUI** | ✅ Local React Native App | ✅ Hot-Swappable SSO & Enterprise Plugins |
| **Reproduction Workflow** | 🔶 JSONL Only | ✅ Interactive Flight Recorder & Jupyter Export |
| **Parallel Engine** | 🔶 Sequential only | ✅ Ray Integration for Distributed Runs |
| **Interactive Triage** | 🔶 Heuristic only | ✅ Human Annotation & Trace Tagging |
| **Advanced Sandbox** | 🔶 Basic Path/Shell Gating| ✅ Docker Containerization & Red-Team Probes |
| **Auth & Governance** | ❌ None | ✅ OIDC SSO, RBAC, Managed Leaderboards |

**Legend:** ✅ Full Capability • 🔶 Basic/OSS Only • ❌ Enterprise Only

**Looking for Production-Grade Reliability?**
The Enterprise Edition guarantees that you can safely evaluate agents over sensitive datasets without exposing credentials or executing dangerous code, backed by mathematical proof of non-repudiation. Contact `ai.eval.harness.contact+enterprise@gmail.com`.

### License
The core of this project is licensed under the **Apache License 2.0**. 
See the [LICENSE](LICENSE) file for details.
