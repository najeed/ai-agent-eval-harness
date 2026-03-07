<!-- README.md (root of the project) -->

# 🤖 AI Agent Evaluation Harness

[![CI](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Tests](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/test.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Contributors](https://img.shields.io/github/contributors/najeed/ai-agent-eval-harness)](https://github.com/najeed/ai-agent-eval-harness/graphs/contributors)

Welcome to the AI Agent Evaluation Harness, an open-source framework for assessing the capabilities of AI agents across a wide range of industries and use cases.

## Mission

Our goal is to create a standardized, community-driven benchmark for AI agent performance. By providing a rich set of industry-specific scenarios and a flexible evaluation runner, we aim to help developers, researchers, and businesses measure and improve their agent-based systems.

## Project Structure

The harness is organized into two main parts:

-   `/industries`: Contains all the evaluation assets (4,400+ scenarios), categorized by 44 industries. Each industry has:
    -   `/scenarios`: Detailed JSON files describing specific tasks and goals for an agent.
    -   `/datasets`: Supporting data files (`.csv`, `.jsonl`, etc.) needed for the scenarios.
-   `/eval-runner`: A modular Python application to load scenarios, execute evaluations, and report on performance.
    -   `engine.py` — Multi-turn conversation loop with agent API
    -   `tool_sandbox.py` — In-process mock tool executor
    -   `loader.py` — Scenario loading with schema validation + CSV/JSONL dataset loading
    -   `metrics.py` — Metric calculations (tool correctness, accuracy, clarity)
    -   `reporter.py` — Console report generation
-   `/sample_agent`: A rule-based Flask agent for the telecom scenario.
-   `/schemas`: JSON Schema definitions for scenario validation.
-   `/tests`: 25 tests across 6 test files.
-   `/docs`: API specs, evaluation guide, and contribution guides.

## Getting Started

### Prerequisites

-   Python 3.8+
-   pip

### Running an Evaluation

1.  Clone and install:
    ```bash
    git clone https://github.com/najeed/ai-agent-eval-harness.git
    cd ai-agent-eval-harness
    pip install -e .
    pip install -r requirements.txt
    ```

2.  Start the sample agent (in a separate terminal):
    ```bash
    python ./sample_agent/agent_app.py
    ```

3.  Run the evaluation:
    ```bash
    python -m eval_runner --industry telecom --scenario technical_support/13814_home_internet_slow_speed.json
    ```

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

## License

This project is licensed under the Apache 2.0 License. See the [LICENSE](LICENSE) file for details.
