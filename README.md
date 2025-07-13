<!-- README.md (root of the project) -->

# AI Agent Evaluation Harness

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
-   (Add any other dependencies here, e.g., `pip install -r requirements.txt`)

### Running an Evaluation

You can run an evaluation from the command line by specifying the industry and the scenario file.

1.  Navigate to the `eval-runner` directory:
    ```bash
    cd eval-runner
    ```

2.  Run the main script:
    ```bash
    python . --industry telecom --scenario customer_service/01_billing_dispute.json
    ```

This will load the specified scenario, run the evaluation engine against it, and print a detailed report to the console.

## How to Contribute

This is a community-driven project, and we welcome contributions! Please see our [CONTRIBUTING.md](CONTRIBUTING.md) file for detailed guidelines on how to add new industries, scenarios, or improve the evaluation engine.

## License

This project is licensed under the Apache 2.0 License. See the [LICENSE](LICENSE) file for details.
