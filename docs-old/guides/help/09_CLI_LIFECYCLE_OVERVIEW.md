# CLI Lifecycle Narrative Guide: The AgentV Industrial Journey

This guide provides a logical, flow-based narrative of the AgentV industrial lifecycle. Instead of a static command list, this document follows the journey of an **Industrial AI Engineer**—from initial project design to production-gate verification.

---

## 🏗️ Stage 1: Design & Scaffolding
*Intent: I want to create new evaluation scenarios and benchmark environments.*

The journey begins here. You are tasked with evaluating a new credit-scoring agent.

1.  **`init`**: First, you scaffold the project structure. This command creates the necessary industry registries, config files, and the `industries/` directory.
2.  **`auto-translate`**: You have a 40-page technical PDF describing the bank's lending policy. You use this command to leverage a local LLM to translate those complex documents into draft **AES (Agent Eval Specification)** JSON.
3.  **`spec-to-eval`**: Using the draft AES, you refine the logic and convert it into a concrete Scenario JSON file ready for the harness.
4.  **`analyze`**: You also want to test against benchmarks from the agent's GitHub repository. `analyze` automatically generates scenarios based on the agent's codebase.
5.  **`mutate`**: To ensure robustness, you generate **adversarial variants** (e.g., prompt injection, edge cases) from your baseline scenarios.
6.  **`scenario`**: Finally, you use the interactive wizard to fine-tune task descriptions and inspect the final artifacts.
7.  **`install`**: Finally, you use this command to download and install official **Scenario Packs** (e.g., Fintech, Healthcare) into your local registry to broaden your test coverage.

---

## 🔍 Stage 2: Discovery & Exploration
*Intent: I want to find existing scenarios, metrics, or registry information.*

Before running tests, you explore the ecosystem to ensure you aren't duplicating work.

1.  **`list`**: You filter the local scenario registry to find existing "Loan Approval" tests.
2.  **`catalog-search`**: You perform a deep search across both global industry catalogs and local repositories.
3.  **`inspect`**: You deep-dive into a specific scenario to display its task breakdown and tooling requirements.
4.  **`list-metrics`**: You review all registered evaluation metrics (e.g., `calculate_accuracy`, `policy_compliance`) to ensure they cover your PRD.
5.  **`taxonomy`**: You consult the official failure taxonomy to understand how the engine will tag potential agent breaches.
6.  **`list-plugins`**: You verify that the necessary security and observability plugins are active in your environment.
7.  **`catalog-refresh`**: You synchronize your local catalog with the latest upstream industry registries to ensure you are testing against the most current standards.

---

## ⚡ Stage 3: Executing Evaluations
*Intent: I want to execute evaluations and identify performance baselines.*

Now, you trigger the engine.

1.  **`run`**: You execute a single, high-priority scenario by its **Scenario ID** (alias) or Benchmark URI to verify the agent's basic logic.
2.  **`evaluate`**: You trigger a batch evaluation across the entire adversarial dataset (by ID or path) to calculate the agent's robust accuracy.
3.  **`quickstart`**: (Optional) You run the 60-second engine demo to verify that the environment is "Ready for Flight."

---

## 🛠️ Stage 4: Debugging & Diagnosis
*Intent: I want to understand why a test failed and experiment with fixes.*

The batch evaluation revealed a 15% failure rate in the "Prompt Injection" cases.

1.  **`replay`**: You replay a failed trace in your terminal to see the turn-by-turn interaction.
2.  **`explain`**: You invoke the forensic engine to diagnose the **root cause** of the breach (e.g., "Policy Violation at Turn 4").
3.  **`failures`**: You search the global Failure Corpus to see if similar patterns have occurred in other industries.
4.  **`record`**: You interact with the agent live and record the session trace to create a new "human-in-the-loop" regression test.
5.  **`playground`**: You launch an interactive REPL to experiment with different agent prompts in the same sandbox environment.

---

## 📊 Stage 5: Reporting & Benchmarking
*Intent: I want to analyze performance and generate shareable artifacts.*

The data is in. Now you need to present it to stakeholders.

1.  **`report`**: You generate a **Premium HTML report** featuring trajectory visualizations and metric heatmaps.
2.  **`leaderboard`**: You generate performance rankings to compare the "baseline" agent against the "hardened" variant.
3.  **`calibrate`**: You measure the agreement between the AI Judge and human auditors to ensure the evaluation is unbiased.

---

## 🛡️ Stage 6: Trust & Verification
*Intent: I want to prove the integrity and compliance of my agent results.*

In industrial environments, results must be theoretically sound and cryptographically verified.

1.  **`verify`**: You verify the cryptographic integrity of the run traces to prove they haven't been tampered with.
2.  **`certify`**: You generate a signed **Verification Certificate (VC)** for the most critical evaluation runs.
3.  **`gate`**: You integrate a "Hard Gate" into the release process—preventing any agent deployment that fails verification.
4.  **`aes`**: You use specification utilities to register the banks new "Loan Ethics" standard into the local manifest.
5.  **`lint`**: You run static analysis to ensure all scenarios comply with the latest industry quality standards.

---

## ⚙️ Stage 7: Automation & Integration
*Intent: I want to scale my evaluations and integrate with CI/CD pipelines.*

Scaling the process for enterprise deployment.

1.  **`ci`**: You generate GitHub Actions workflow templates to automate evaluations on every Pull Request.
2.  **`export`**: You export the validated traces to a HuggingFace dataset for further fine-tuning.
3.  **`import-drift`**: When you detect a failure in production, you import those logs back into AgentV as new scenarios for regression testing.
4.  **`registry`**: You synchronize your local industry standards with the global registry.

---

## 🛂 Stage 8: Maintenance & Control
*Intent: I want to manage the environment, plugins, and system health.*

Keeping the engine tuned and governed.

1.  **`console`**: You launch the **Visual Suite** to monitor live trajectories and edit scenarios in a React-based UI.
2.  **`contribute`**: You use the wizard to contribute your new "Loan Ethics" scenario pack back to the community.
3.  **`cleanup-runs`**: You prune old log artifacts to maintain a clean workspace.
4.  **`doctor`**: You audit the system environment to ensure all dependencies and forensic markers are healthy.
5.  **`plugin`**: You manage the specialized "Finance Guardrail" plugins that protect the evaluation sandbox.

---

## 🚀 Stage 9: Extension & Customization
*Intent: I want to add my own commands to the AgentV ecosystem.*

Starting with **v1.5.1**, the CLI is no longer a closed monolith. It uses an **Industrial Discovery Pattern** based on Python Entry Points.

1.  **Extensible Commands**: You can now build separate Python packages that "plug in" to the `agentv` command without modifying the Core repository.
2.  **Zero-Touch Discovery**: Commands registered via `pyproject.toml` are automatically discovered at runtime.
3.  **Unified Dispatch**: All commands share the same functional dispatcher, ensuring that Enterprise tools feel like native parts of the harness.

---

**Summary**: By following this intent-based flow, AgentV ensures that every step—from authoring to deployment—is auditable, deterministic, and industrial-grade.
