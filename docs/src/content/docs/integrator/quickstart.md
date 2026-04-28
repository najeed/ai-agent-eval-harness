---
title: Quickstart Masterclass
description: Your first deterministic evaluation in under 120 seconds.
---

import { Steps } from '@astrojs/starlight/components';

# Zero-Key Quickstart

Welcome to AgentV. This guide gets you from a fresh installation to your first **Forensic Evaluation** in under two minutes. No API keys, cloud accounts, or complex configurations are required for this initial walkthrough.

## 🏁 The 120-Second Sprint

<Steps>

1.  **Environment Setup**  
    Create a clean virtual environment and install the harness in editable mode.
    ```bash
    python -m venv venv
    venv\Scripts\activate
    pip install -e ".[dev]"
    ```

2.  **Initialize the Industrial Corpus**  
    Scaffold the necessary local directories and download a lightweight, deterministic evaluation suite.
    ```bash
    agentv quickstart
    ```

3.  **Execute a Deterministic Run**  
    Run a pre-configured scenario using the **Zero-Temperature Mock Adapter**. This verifies your local routing and event bus without incurring LLM costs.
    ```bash
    agentv evaluate --path industries/finance/scenarios/loan_approval.json
    ```

4.  **Visual Triage**  
    Launch the **Integrated Console** to inspect the behavioral DNA of your run.
    ```bash
    agentv console
    ```
    Open [http://localhost:5000](http://localhost:5000) in your browser to see the trajectory, state deltas, and the forensic ledger.

</Steps>

---

## 🔍 What Just Happened?

When you ran `evaluate`, the AgentV engine executed several industrial-grade protocols:

- **Isolated Routing**: The engine consulted `.aes/config/routing/manifest.json` to map the scenario's requirements to a local simulator.
- **Event-Driven Observation**: Every tool call and reasoning step was emitted to the [Global Event Bus](/builder/architecture/), allowing the dashboard to mirror the execution in real-time.
- **Forensic Ledger Creation**: A SHA-256 hash was generated for the trace, binding the results to your local **Identity Registry**.

## 🚀 Next Steps

- [**The Scholar Path**](/scholar/): Learn about Deterministic Seeds and Academic Benchmarks.
- [**The Architect Path**](/builder/architecture/): Deep-dive into Singleton Process Guards and Dynamic CLI Dispatch.
- [**The Auditor Path**](/auditor/trust-protocol/): Implement the v1.6.0 Trust Protocol for CI/CD gating.

> [!TIP]
> **Note**: Now that your environment is verified, you can swap the mock adapter for a live model by setting your `OPENAI_API_KEY` or `GEMINI_API_KEY` and updating your [Routing Registry](/spec/routing_v1/).
