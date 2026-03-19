
<!-- CONTRIBUTING.md -->

# Contributing to AI-Agent-Eval-Harness

Thank you for your interest in building the industry standard for agentic reliability.

---

## ⚖️ Legal & Licensing

### 1. The Apache License 2.0
By contributing to this repository, you acknowledge that this project is licensed under the **Apache License 2.0**.

### 2. Developer Certificate of Origin (DCO)
To simplify contributions, we use the **DCO** (Developer Certificate of Origin) model instead of a proprietary CLA. By adding a `Signed-off-by` line to your commit messages, you certify that you have the right to submit the work under the project's license.

To sign a commit:
```bash
git commit -s -m "Your commit message"
```

---

## 🏗️ How to Contribute

### 1. Adding New Industries & Scenarios
- **Schema Compliance**: All JSON files must pass the validation checks via `eval-harness aes validate --path <path>`.
- **Scaffolding**: Use `eval-harness init --dir <name> --industry <ind>` to bootstrap a new benchmark suite automatically linked to a synthetic CSV dataset.
- **Quality Verification**: All scenarios must pass the quality linter (`eval-harness lint --path <path>`). We target a score of **90+** for all official industry libraries.
- **Execution**: Ensure your scenario runs correctly with `eval-harness evaluate --path <your_path>`. The harness now supports **Path Decoupling**, allowing you to host and run benchmarks from any directory without repository-internal dependencies.

### 2. The Zero-Touch Core Philosophy
We strictly adhere to a **Zero-Touch Core** architectural mandate. Pull Requests that modify the core orchestration (`eval_runner/runner.py`, `eval_runner/metrics.py`) to handle edge cases or custom platforms will generally be rejected.
- **Decoupling**: Keep orchestration (Runner), state (Session), and observation (EventEmitter) separated.
- **Extensibility**: All custom business logic, LLM providers, and bespoke metrics MUST be implemented as a plugin.
- **Immutability**: `TurnContext` and `EvaluationContext` are frozen data structures. Use `dataclasses.replace()` for updates rather than mutating state directly.
- **Typing**: All Python code must be fully type-hinted using `mypy` standards.
- **Testing**: New features must include a unit test in the `/tests` directory.

### 3. Extending via Plugins
The Zero-Touch Core is designed to be extended without core PRs.
- **Lifecycle Hooks**: Subscribe to `before_evaluation`, `on_agent_turn_start`, `on_turn_end`, `on_metrics_calculated`, and `after_evaluation`.
- **Interception**: Use `on_tool_request` to enforce safety or HITL proxies. Return `False` to block a tool call.
- **CLI Commands**: Use `on_register_commands` to register namespaced CLI subcommands (under `eval-harness plugin <name>`).
- **Event Bus**: Use `EventEmitter.subscribe(callback)` for passive monitoring.
- **Entry Points**: Register your plugins in your `pyproject.toml` under `eval_runner.plugins`.
- **Timeouts**: All plugin hooks are subject to a 5-second timeout to prevent hang conditions.

---

## 🚀 The Pull Request Process

1. **Fork and Branch**: Create a feature branch from `main`.
2. **Sign the DCO**: Ensure every commit is signed with `git commit -s`.
3. **Run Local Evals**: Verify your changes by running a sample evaluation.
4. **Documentation**: Update the `README.md` or industry docs if your changes affect the user interface or scenario logic.

---

## 👑 Code of Conduct
Focus on technical excellence. Submissions that do not meet the architectural standards (modular, typed, tested) will be closed with feedback. 

---

**Questions?** Reach out via GitHub Discussions or open an Issue.
