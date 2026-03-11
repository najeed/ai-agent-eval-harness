<!-- README.md (root of the project) -->

# 🤖 AI Agent Evaluation Harness

[![CI](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: BSL 1.1](https://img.shields.io/badge/License-BSL%201.1-orange.svg)](LICENSE)
[![Contributors](https://img.shields.io/github/contributors/najeed/ai-agent-eval-harness)](https://github.com/najeed/ai-agent-eval-harness/graphs/contributors)

Welcome to the AI Agent Evaluation Harness, the open-source reliability framework for AI agents: evaluation, replay debugging, drift detection, and failure datasets across a wide range of industries and use cases.

| Attribute | Specification |
| :--- | :--- |
| **Architect** | [Najeed Ahmed Khan](https://github.com/najeed) |
| **License** | **BSL 1.1** (Converts to Apache 2.0 in 2032) |
| **Status** | Production-Ready Framework |
| **Core Goal** | Eliminating the "Agentic Reliability Gap" |
| **Contribution** | Individual CLA Required |

## Mission

Our goal is to create a standardized, community-driven benchmark for AI agent performance. By providing a rich set of industry-specific scenarios and a flexible evaluation runner, we aim to help developers, researchers, and businesses measure and improve their agent-based systems.

The harness is organized into the following key components:

-   `/industries`: Evaluation assets (4,400+ scenarios) categorized by 44 industries.
-   `/eval_runner`: Modular Core Engine (Multi-turn loop, Sandbox, Metrics, Simulators, Mutator).
-   `/ui` & `/dashboard`: Frontend visualization tools for agent traces and analytical insights.
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
-   **Ollama (optional, for Local LLM Evaluation)**:
    -   Download from [ollama.com](https://ollama.com).

### 🚀 60-Second Quickstart

The fastest way to see the harness in action:

```bash
# 1. Clone the repository
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness

# 2. Set up a virtual environment (Recommended)
python -m venv venv
venv\Scripts\activate  # On Windows
# source venv/bin/activate  # On macOS/Linux

# 3. Install the package in editable mode
pip install -e .

# 4. Run the Quickstart Demo
eval-harness quickstart
```

**What it does:** Spawns a mock sample agent, runs a troubleshooting evaluation, and generates a rich HTML report in `reports/`.

*(Optional Full Lab Mode):* For the complete dashboard and database experience, you can use `docker-compose up --build`.

### 🛠 Manual Evaluation (Running the Sample Agent)

1.  **Start your Agent**: The framework includes a reference agent for testing.
    ```bash
    python sample_agent/agent_app.py
    ```
2.  **Set Endpoint**: Point the harness to your agent's webhook.
    ```bash
    set AGENT_API_URL=http://localhost:5001/execute_task   # Windows
    export AGENT_API_URL=http://localhost:5001/execute_task # Mac/Linux
    ```
3.  **Run Batch Evaluation**: 
    ```bash
    eval-harness evaluate --path industries/telecom
    ```

---

## 🚀 At a Glance (v1.0 RC)

- **Evaluation Specification (AES)**: Standardized YAML/Markdown benchmarks for agents.
- **Benchmark Ecosystem**: Native loaders and adapters for community benchmarks like GAIA and AssistantBench.
- **Pluggable Architecture**: Extend anything via Python plugins, with out-of-the-box framework adapters for LangGraph and CrewAI.
- **Tool Sandbox**: Governance-controlled execution of real or mock tools.
- **Semantic Bridge & Distribution**: Ingest production traces (`import-drift`), analyze failures (`triage`), and export datasets to HuggingFace (`export`).
- **Research-Grade Orchestration**: Support for `pass@k`, non-linear trajectories (`fork()`), and HITL.
- **Robust Metrics**: 10+ built-in metrics (Tool Correctness, State Parity, Policy Compliance).

## 🛠️ CLI Highlights

```bash
# Run evaluations
eval-harness evaluate --path scenarios/telecom/

# Import production drift
eval-harness import-drift --input trace.json --industry telecom

# Debug with Flight Recorder
eval-harness replay runs/run.jsonl

# Interactive Playground
eval-harness playground --agent http://localhost:5001

# Export to HuggingFace
eval-harness export --input runs/run.jsonl --format hf --output dataset.json
```
*See the full [CLI Reference](docs/cli_reference.md) for more.*

## 🏗 Zero-Touch Core Architecture

The harness is built on a decoupled, event-driven architecture that allows Enterprise integrations to be hot-swapped without core modifications.

- **EventEmitter Bus**: Passive observation of every turn, tool call, and state change.
- **Pluggable Runners**: Strategy-based orchestration for multi-attempt (`pass@k`) or interactive evaluations.
- **Interception Hooks**: Plugins can now intercept and block tool calls (`on_tool_request`) or register custom adapters.
- **Native HITL Support**: Built-in support for pausing evaluation for human intervention via the `human` adapter.
- **Non-Linear Trajectories**: Support for branching and forking trajectories (`fork()`) in `SessionManager` for research-grade evaluations.
- **Advanced Discovery**: Plugin-driven registry for third-party agent adapters via the `on_discover_adapters` hook.
- **Immutable Contexts**: Ensures plugins cannot introduce side-effects into the core engine state.

### 🌟 Productivity Utilities
- `doctor`: Environment health checker.
- `report`: Rich HTML reporting with interactive Mermaid trajectories.
- `record` & `playground`: Interaction capture and REPL experimentation.
- `spec-to-eval`: Convert Markdown PRDs/Specs into executable JSON scenarios.
- `scenario generate`: Interactive scaffolding for authoring tests.

### Running Tests

```bash
pytest tests/ -v -p no:plugin_gateway
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint URL |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |
| `OPENAI_API_KEY` | *(None)* | Required if using LLM-as-a-Judge metrics |

### 🚨 Run Trace Warning
All evaluation execution logs are appended to `runs/run.jsonl`. Because this acts as an immutable flight recorder, the file will grow continuously. It is recommended to use the built-in trace rotation or periodically clean up this directory.

### 🐛 Troubleshooting

- **`ConnectionRefusedError`**: The harness cannot reach the agent. Ensure `AGENT_API_URL` is set correctly and the agent API is running.
- **`GoException: no routes for location`**: Occurs in the Flutter UI dashboard if the router isn't rebuilt. Re-run `flutter pub run build_runner build`.
- **`PluginTimeoutError`**: A registered plugin took too long to execute a hook. Check your plugin logic or increase the timeout.
- **`Invalid JSON Error (LLM)`**: The `auto-translate` command expects strict JSON. Ensure your local Ollama model (e.g., `llama3`) is running and capable of JSON mode.

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
- 🏭 [Contribute new industries](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=industry_request.md)
- 🎯 [Create evaluation scenarios](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=scenario_contribution.md)

### Contributors
Thanks to all our contributors! 🙌

<a href="https://github.com/najeed/ai-agent-eval-harness/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=najeed/ai-agent-eval-harness" />
</a>

## Licensing & Editions

This project follows an **Open Core** model.

| Feature | Community Edition (OSS) | Enterprise Edition |
| :--- | :--- | :--- |
| Core Eval Engine | ✅ Included (BSL 1.1) | ✅ Included |
| Industry JSON Scenarios | ✅ 4,400+ included | ✅ Priority Updates |
| Docker Support | ✅ Included | ✅ High-Scale Clusters |
| Adversarial Simulations | ❌ No | ✅ Advanced Red-Teaming |
| Visual Dashboard | ❌ CLI Only | ✅ Web UI & Analytics |

Looking for Production-Grade Reliability?
The Enterprise Edition includes path-efficiency scoring, automated red-teaming, and real-time grounding proxies. Contact ai.eval.harness.contact+enterprise@gmail.com.

### License
The core of this project is licensed under the **Business Source License 1.1**. 
- **For Developers:** It is free to use for testing, research, and startups under $5M revenue.
- **For Enterprise:** A commercial license is required for high-scale production and competing services.
- **Future:** This code will automatically transition to **Apache 2.0** on January 1, 2032.
See the [LICENSE](LICENSE) file for details.
