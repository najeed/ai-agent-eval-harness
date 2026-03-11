
<!-- CONTRIBUTING.md -->

# Contributing to AI-Agent-Eval-Harness

Thank you for your interest in building the industry standard for agentic reliability.

---

## ⚖️ Legal & Licensing

### 1. The Business Source License (BSL) 1.1
By contributing to this repository, you acknowledge that this project is licensed under the **BSL 1.1**. While the core is open for developers and startups, it converts to Apache 2.0 on January 1, 2032. 

### 2. Mandatory CLA
This repository uses **CLA Assistant** to manage contributor agreements. You **must** sign the Individual Contributor License Agreement (CLA) before your Pull Request can be reviewed.

---

## 🏗️ How to Contribute

### 1. Adding New Industries & Scenarios
- **Schema Compliance**: All JSON files must pass the validation checks in `/schemas`.
- **Scaffolding**: Use `eval-harness scenario generate` to bootstrap new scenarios.
- **Verification**: Ensure your scenario runs correctly with `eval-harness run industries/<ind>/scenarios/<file>.json`.

### 2. Improving the Zero-Touch Core
The core engine must remain fast, modular, and lightweight.
- **Decoupling**: Keep orchestration (Runner), state (Session), and observation (EventEmitter) separated.
- **Immutability**: `TurnContext` and `EvaluationContext` are frozen. Use `dataclasses.replace()` for updates.
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
2. **Sign the CLA**: The bot will prompt you once the PR is opened.
3. **Run Local Evals**: Verify your changes by running a sample evaluation.
4. **Documentation**: Update the `README.md` or industry docs if your changes affect the user interface or scenario logic.

---

## 👑 Code of Conduct
Focus on technical excellence. Submissions that do not meet the architectural standards (modular, typed, tested) will be closed with feedback. 

---

**Questions?** Reach out via GitHub Discussions or open an Issue.
