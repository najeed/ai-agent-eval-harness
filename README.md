<!-- README.md (root of the project) -->

# 🤖 AI Agent Evaluation Harness

[![CI](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Tests](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/test.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
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
-   **Ollama (for Local LLM Evaluation)**:
    -   Download from [ollama.com](https://ollama.com).
    -   Install and run the Ollama server.
    -   Pull the default model (Llama3):
        ```bash
        ollama pull llama3
        ```
    -   (Optional) Set `OLLAMA_HOST` if running on a non-standard port or remote machine.

### Running an Evaluation

1.  **Clone and install locally**:
    ```bash
    git clone https://github.com/najeed/ai-agent-eval-harness.git
    cd ai-agent-eval-harness
    pip install -e .
    pip install -r requirements.txt
    ```

2.  **OR Run via Docker (Instant Lab)**:
    Start the entire lab (harness, agent, and dashboard):
    ```bash
    docker-compose up -d
    ```

3.  **Run evaluations inside the Lab**:
    ```bash
    docker-compose exec harness eval-harness run --industry telecom --export
    ```

4.  **Visualize results**:
    Open the dashboard at [http://localhost:8501](http://localhost:8501) to explore trajectories and metrics.
    The `--export` flag will generate a detailed JSON trajectory in the `reports/trajectories/` directory.

### Advanced Features
- **AES Specification (Foundational)**: Industry-standard format for shareable benchmarks (AES v0.1).
- **Universal Plugin Architecture**: Extend the engine without touching the core. Register custom Metrics, Loaders, or Agent Adapters via `entry_points`.
- **Lifecycle Hooks**: Inject logic at key stages: `before_evaluation`, `on_turn_end`, and `after_evaluation`.
- **Path Parsimony**: Evaluations automatically score agents on efficiency (fewer turns = higher score).
- **Trajectory Visualization**: Failed tasks include a Mermaid decision tree in the report to help debug "wrong turns."
- **Edge-Case Triage**: Automatically categorize failures (e.g., `CONNECTION_ERROR`, `POLICY_VIOLATION`) using the built-in Triage Library.
- **Drift Management**: Import production traces directly as regression test cases using `import-drift`.
- **Simulation Lab**: State-of-the-art simulation shims for Git and API environments, enabling complex multi-turn evaluations without external dependencies.
- **Research-Grade Metrics**: Native support for `pass@k`, `Success Consistency`, `Semantic Stability`, and `Safety Guardrails` (PII, Refusal).
- **Adversarial Mutation**: Automatically generate typo, ambiguity, and injection variants of benchmarks to test agent robustness.

### Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_API_URL` | `http://localhost:5001/execute_task` | Agent endpoint URL |
| `EVAL_MAX_TURNS` | `5` | Max conversation turns per task |

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
