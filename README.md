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

-   `/industries`: Contains all the evaluation assets, categorized by industry. Each industry has:
    -   `/scenarios`: Detailed JSON files describing specific tasks and goals for an agent.
    -   `/datasets`: Supporting data files (`.csv`, `.jsonl`, etc.) needed for the scenarios.
-   `/eval-runner`: A modular Python application to load scenarios, execute evaluations, and report on performance.

## Getting Started

### Prerequisites

-   Python 3.8+
-   A curious and tinkering spirit

### Running an Evaluation

You can run an evaluation from the command line by specifying the industry and the scenario file or folder. If a folder is specified, it iterates over all the files in that folder.

1.  Navigate to the parent `ai-agent-eval-harness` directory:
    ```bash
    cd /path/to/ai-agent-eval-harness
    ```

2.  (Optional) Build the eval_runner module:
    ```bash
    pip install -e .
    pip install Flask requests
    ```

3.  From a different terminal, run the server to instantiate the example agent:
    ```bash
    python ./sample_agent/agent_app.py
    ```
    Test if the agent is running by issuing a curl request from another terminal:
    ```bash
    curl -X POST http://localhost:5001/execute_task -H "Content-Type: application/json" -d "{\"task_description\": \"First, identify the customer and their current speed tier.\"}"
    ```
    If the server is up, you should see a response similar to: 
    ```
    {"action":"call_tool","summary":"Identified customer Jane Doe on plan 100 Mbps Fiber.","tool_name":"get_customer_details","tool_output":{"customer_name":"Jane Doe","plan":"100 Mbps Fiber","status":"success"},"tool_params":{"customer_id":"cust_123"}}
    ```

4.  Run the main script:
    ```bash
    python -m eval_runner --industry telecom --scenario technical_support/13814_home_internet_slow_speed.json
    ```

This will load the specified scenario(s), run the evaluation engine against the criteria, and print a detailed report to the console.

### Export Results

You can export evaluation results in multiple formats for analysis, reporting, and sharing:

#### CSV Export
Export results in CSV format for data analysis and Excel compatibility:
```bash
python -m eval_runner --industry telecom --scenario technical_support/13814_home_internet_slow_speed.json --export csv --output results.csv
```

#### JSON Export
Export results in JSON format for programmatic processing:
```bash
python -m eval_runner --industry telecom --scenario technical_support/13814_home_internet_slow_speed.json --export json --output results.json
```

#### HTML Export
Export results in HTML format for human-readable reports:
```bash
python -m eval_runner --industry telecom --scenario technical_support/13814_home_internet_slow_speed.json --export html --output report.html
```

For HTML reports with visualization charts:
```bash
python -m eval_runner --industry telecom --scenario technical_support/13814_home_internet_slow_speed.json --export html --output report.html --include-charts
```

**Note:** If `--output` is not specified, files will be automatically named using the scenario ID and timestamp.

### Programmatic API

You can also use the export functionality programmatically:

```python
from eval_runner import engine, loader

# Load and run evaluation
scenario = loader.load_scenario("path/to/scenario.json")
results = engine.run_evaluation(scenario)

# Export in different formats
results.export_csv("results.csv")
results.export_json("results.json")
results.export_html("report.html", include_charts=True)

# Access summary statistics
summary = results.get_summary_stats()
print(f"Success rate: {summary['success_rate']}%")
```

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
