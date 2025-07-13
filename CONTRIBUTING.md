
<!-- CONTRIBUTING.md -->

# Contributing to the AI Agent Evaluation Harness

First off, thank you for considering contributing! Your help is essential for building a comprehensive and valuable resource for the AI community.

## Code of Conduct

This project and everyone participating in it is governed by our Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior. (TODO: Add a link to a Code of Conduct file).

## How Can I Contribute?

There are many ways to contribute, from adding new evaluation scenarios to improving the core evaluation engine.

### Adding a New Scenario

This is one of the most valuable ways to contribute.

1.  **Choose an Industry and Use Case:** Find the relevant industry folder in `/industries`. If the use case folder (e.g., `customer_service`) doesn't exist, create it.
2.  **Create a JSON file:** Follow the structure of existing scenarios (see `industries/telecom/scenarios/customer_service/01_billing_dispute.json` as a template).
3.  **Define Tasks:** Break down the scenario into a sequence of clear, testable tasks.
4.  **Define Success Criteria:** For each task, specify the metrics and thresholds that define success.
5.  **Submit a Pull Request:** Create a PR with your new scenario file. Please include a clear description of the scenario in the PR description.

### Adding a New Industry

We are always looking to expand to new industries! Please follow the guide here: [docs/guides/02_ADDING_AN_INDUSTRY.md](docs/guides/02_ADDING_AN_INDUSTRY.md).

### Improving the `eval-runner`

If you have ideas for new metrics, reporting formats, or improvements to the evaluation logic, we'd love to see them.

1.  Fork the repository.
2.  Create a new branch for your feature (`git checkout -b feature/new-metric`).
3.  Make your changes to the code in the `/eval-runner` directory.
4.  Add comments and docstrings to any new functions.
5.  Submit a Pull Request with a clear description of your changes.

## Pull Request Process

1.  Ensure any new code is commented and follows the existing style.
2.  Update the README.md or other documentation if your changes require it.
3.  Increase the version numbers in any examples and the README.md to the new version that this Pull Request would represent. The versioning scheme we use is [SemVer](http://semver.org/).
4.  Your PR will be reviewed by a maintainer, who may ask for changes.

We look forward to your contributions!
