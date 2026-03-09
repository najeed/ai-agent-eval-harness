
<!-- CONTRIBUTING.md -->

# Contributing to AI-Agent-Eval-Harness

Thank you for your interest in building the industry standard for agentic reliability. This is a high-standard project aimed at changing how the world measures AI intelligence. To maintain the integrity of the harness, we have a rigorous contribution process.

---

## ⚖️ Legal & Licensing (Required Reading)

### 1. The Business Source License (BSL) 1.1
By contributing to this repository, you acknowledge that this project is licensed under the **BSL 1.1**. While the core is open for developers and startups, it converts to Apache 2.0 on January 1, 2032. 

### 2. Mandatory CLA
This repository uses **CLA Assistant** to manage contributor agreements. You **must** sign the Individual Contributor License Agreement (CLA) before your Pull Request can be reviewed. This ensures that [Najeed Ahmed Khan] retains the right to include community improvements in both the open-source core and future enterprise modules.

---

## 🛠️ How to Contribute

### 🏗️ Adding New Industries & Scenarios
We have 4,400+ scenarios, but the world changes fast. If you are adding a new industry:
1. **Schema Compliance:** All JSON files must pass the validation checks in `/schemas`.
2. **Grounding Datasets:** If a scenario requires external data, include it in the `/datasets` folder for that industry.
3. **Efficiency Baselines:** Every scenario should include a "Successful Path" with a recorded number of tool calls.

### 💻 Improving the Eval-Runner
The core engine must remain fast, modular, and lightweight.
- **No Heavy Dependencies:** Prevent adding large libraries to the core `requirements.txt`.
- **Typing:** All Python code must be fully type-hinted using `mypy` standards.
- **Testing:** New features must include a unit test in the `/tests` directory.

### 🔌 Extending via Plugins (Milestone 11+)
You can now extend OpenCore without touching the primary engine logic.
- **Lifecycle Hooks:** Plugins can subscribe to `before_evaluation`, `on_turn_end`, and `after_evaluation`.
- **Registries:** Use the provided registries to add custom metrics, loaders, or agent adapters.
- **Entry Points:** Register your plugins in your `pyproject.toml` under the `eval_runner.plugins` entry point group.
- **Context Awareness:** Plugins receive typed `EvaluationContext` or `TurnContext` objects, ensuring stable integrations.

---

## 🚀 The Pull Request Process

1. **Fork and Branch:** Create a feature branch from `main`.
2. **Sign the CLA:** The bot will prompt you once the PR is opened.
3. **Run Local Evals:** Verify your changes by running a sample evaluation:
   `python -m eval_runner --industry telecom --scenario [your_new_scenario].json`
4. **Documentation:** Update the `README.md` or industry docs if your changes affect the user interface or scenario logic.

---

## 👑 Code of Conduct
This is a professional project for serious architects. Be clever, be direct, and focus on technical excellence. Submissions that do not meet the architectural standards of this project will be closed with feedback. 

This project and everyone participating in it is governed by our Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior. [docs/CODE_OF_CONDUCT.md](docs/CODE_OF_CONDUCT.md)[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](docs/CODE_OF_CONDUCT.md)

---

**Questions?** Reach out via GitHub Discussions or open an Issue.

