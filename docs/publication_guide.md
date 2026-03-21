# User Guide: Advanced Publication Suite

This guide provides step-by-step instructions and examples for using the Advanced Publication Suite to conduct evaluations, aggregate results, and generate professional leaderboards.

## Table of Contents
1. [Setup & Configuration](#setup-configuration)
2. [Directory Structure: scenarios vs industries](#directory-structure-scenarios-vs-industries)
3. [Quick Start: Pilot Mode](#quick-start-pilot-mode)
4. [Agent Protocols & Adapters](#agent-protocols-adapters)
5. [Standard Execution](#standard-execution)
6. [Advanced Options](#advanced-options)
7. [Deep Dive on Seeds](#deep-dive-on-seeds)
8. [Understanding Outputs](#understanding-outputs)

---

## Setup & Configuration

The suite is driven by `config.yaml` in the project root. Ensure your pricing and performance thresholds are set correctly:

```yaml
default_runs: 100
pilot_runs: 5
parallel_workers: 4
pricing:
  openai_gpt4o: 5.0     # USD per 1M tokens
  claude_sonnet: 3.0
  gemini_pro: 2.0
regression_threshold: 0.03
```

## Directory Structure: scenarios vs industries

Understanding the relationship between these two directories is key to finding and managing your evaluation data:

### `/industries` (The Master Library)
Think of this as your **Industry Vertical Source Library**. It contains the "raw gold" for 44 different sectors (Finance, Healthcare, Telecom, etc.).
- **Sub-folders**: Each industry has `/datasets` (raw data like CSVs) and `/scenarios` (task-specific evaluation definitions).
- **Purpose**: Permanent storage of industry-specific benchmarks and templates.

### `/scenarios` (The Execution Index)
This is the **Active Evaluation Layer**. This is where the harness looks when you start a run.
- **`index.json`**: A master catalog that maps unique Scenario IDs (e.g., `wholesale-om-14310`) to their physical JSON files located deep within the `/industries` library.
- **Top-level JSONs**: Contains demo scenarios (e.g., `luna_demo.json`) and generated scenarios ready for immediate execution.
- **Purpose**: Providng a flat, searchable interface for the CLI to target specific evaluation tasks.

---

## Quick Start: Pilot Mode

Use **Pilot Mode** for rapid iteration, testing new scenarios, or verifying your agent integration. It runs 5 iterations across a 10-scenario subset.

### Example: Running a pilot for a new adapter
```bash
python scripts/publication_suite/publication_suite.py --mode pilot --agent-name "GPT-4o-Pilot" --agent "http://localhost:5001/execute"
```
**Target Time:** 3-5 minutes (serial execution to ensure clean Flight Recorder traces).
**Outcome:** Generates a `pilot_preview.html` and statistical summary based on 25-50 total runs.

---

## Agent Protocols & Adapters

The harness is designed to be agent-agnostic, supporting a wide range of communication protocols and ecosystem-specific adapters.

### 1. Standard Protocols
These are built-in and require no additional plugins.

| Protocol | Description | Required CLI Flag | Example |
| :--- | :--- | :--- | :--- |
| **HTTP** | Communicates with an agent's web API. | `--agent <URL>` | `--protocol http --agent http://localhost:5001/execute` |
| **Local** | Spawns a local process. Uses stdin/stdout for JSON. | `--agent-cmd <CMD>` | `--protocol local --agent-cmd "python my_agent.py"` |
| **Socket** | Communicates over TCP or Unix sockets. | `--agent-socket <ADDR>` | `--protocol socket --agent-socket tcp:127.0.0.1:9000` |

### 2. Ecosystem Adapters
The harness includes built-in adapters for major AI frameworks. These often use specialized protocols prefixes.

| Framework | Protocol Prefix | Key Env Variables / Config |
| :--- | :--- | :--- |
| **OpenAI** | `openai://` | `OPENAI_API_KEY` |
| **Claude** | `claude://` | `ANTHROPIC_API_KEY` |
| **Gemini** | `gemini://` | `GOOGLE_API_KEY` |
| **Grok** | `grok://` | `XAI_API_KEY` |
| **Ollama** | `ollama://` | (Requires local Ollama server) |
| **LangChain** | `langchain://` | Varies by chain configuration |
| **LangGraph** | `langgraph://` | Support for state-aware graphs |
| **AutoGen** | `autogen://` | Multi-agent conversation hooks |
| **CrewAI** | `crewai://` | Role-based agent orchestration |

---

## Standard Execution

Run a full benchmarking campaign (default 100 runs per scenario) to generate publishable results with 95% confidence intervals.

### Example: Full scale evaluation with parallel workers
```bash
python scripts/publication_suite/publication_suite.py --mode standard --agent-name "Claude-3.5-Sonnet-v1" --parallel 8
```
**Outcome:** Generates a full `leaderboard.html` and a signed artifact bundle.

---

## Advanced Options

### Slicing by Scenario Path
Target specific verticals or difficulty tiers by pointing to a specific subdirectory.
```bash
python scripts/publication_suite/publication_suite.py --path scenarios/finance/high_difficulty/
```

### Specifying Agent Protocols
Support for different agent communication protocols.
```bash
python scripts/publication_suite/publication_suite.py --protocol socket --agent "127.0.0.1:9000"
```

### Reproducibility with Seeds
The conductor generates deterministic seeds per batch, but you can override the base seed.
```bash
python scripts/publication_suite/conductor.py --seed 12345 --agent-name "Reproducible-Agent"
```

---

## Deep Dive on Seeds

Reproducibility is a cornerstone of scientific evaluation. The harness uses **Seeds** (deterministic random values) to ensure that stochastic processes remain consistent across re-runs.

### Why Seeds Matter
AI agents are often non-deterministic due to model temperature and randomized data sampling. Seeds allow you to "freeze" this randomness.

### How Seeds Work in the Harness
1. **Global Initialization**: When you provide `--seed 12345`, the harness initializes Python's `random`, `numpy`, and the `PYTHONHASHSEED` environment variable.
2. **Deterministic Offsets**: For multi-run batches, the Conductor applies a unique but predictable offset for each run: `Final Seed = Base Seed + Run Index`.
3. **Reproducible Failure Analysis**: Every failed run in the `manifest.json` includes the exact seed used. You can re-run that specific scenario with the same seed to observe the exact same failure trace for debugging.

### Role in Leaderboards
Using consistent seeds across different adapters ensures that they are evaluated against the **exact same conditions**, making your leaderboard a "fair fight".

---

## ⚔️ Model Wars: Multi-Agent Benchmarking
The suite supports **Model Wars** mode, allowing you to benchmark multiple agents against the same scenario library in a single pass. This produces a unified comparative leaderboard.

### 1. Define Agent Inventory
To use Model Wars, you must provide an **Agent Inventory** YAML file (Default: `scripts/publication_suite/agents_inventory.yaml`). This file defines the fleet of agents you wish to compare.
```yaml
agents:
  - name: "GPT-4o"
    protocol: "openai"
    agent: "https://api.openai.com/v1/chat/completions"
  
  - name: "Local-Llama3"
    protocol: "ollama"
    agent: "http://localhost:11434"
```

### 2. Run Comparative Benchmark
Use the `--compare` flag:
```bash
python scripts/publication_suite/publication_suite.py --mode pilot --compare scripts/publication_suite/agents_inventory.yaml
```

### 3. Review Comparative Leaderboard
The suite will generate a single `leaderboard.html` (in the `results/` root) containing:
- **Head-to-Head Stats**: Normalized pass rates, latency, and cost per agent.
- **Robustness Radar**: Comparative visualization of success consistency.
- **Cross-Model Breakdown**: Performance of every agent across every scenario in a unified grid.

---

## Understanding Outputs

Every execution creates a unique batch directory in `results/batch_YYYYMMDD_HHMMSS/`.

### Directory Structure:
- `manifest.json`: The "flight manifest" linking scenarios, seeds, and individual run logs.
- `run_XXX.jsonl`: Individual Flight Recorder traces for every single run.
- `aggregated_results.json`: Statistical summary (pass@k, CI 95%, cost, taxonomy).
- `leaderboard.html` / `pilot_preview.html`: Professional visual report.
- `publication_artifact_bundle.zip`: The signed package for regulatory submission.
- `audit_manifest.json`: SHA-256 hashes of all artifacts for auditing.

### Contents of the Signed Artifact Bundle
The `publication_artifact_bundle.zip` is powered by the core **ArtifactPlugin**. It ensures portability and auditability via the following components:

1. **`aggregated_results.json`**: The core statistical dataset.
2. **`leaderboard.html`**: The full visual dashboard for offline viewing.
3. **`manifest.json`**: The complete mapping of the run batch (scenarios, seeds, run IDs).
4. **`audit_manifest.json` (External companion)**: Created by the core `ArtifactPlugin`, this file contains SHA-256 integrity hashes for every file in the bundle. 

> [!IMPORTANT]
> Because this bundling logic is part of the **Zero-Touch Core**, it serves as an immutable "Source of Truth" for regulatory or public disclosures. The Publication Suite simply provides a professional interface to these core compliance hooks.

---

## Failure Taxonomy legend
If you see failures in your leaderboard, they are mapped as follows:
- **tool_call_error**: Environmental/API error during tool execution.
- **state_parity_mismatch**: Agent reached a valid state but failed tool-specific parity checks.
- **hallucination**: Agent attempted to call non-existent tools or hallucinated data.
- **timeout**: Agent hit the maximum turn limit (default 10).
- **sandbox_breach**: Policy violation detected in tool execution.
- **partial_pass**: Multi-step scenario where some, but not all, requirements were met.
