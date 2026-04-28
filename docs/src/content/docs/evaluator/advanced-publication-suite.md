---
title: Advanced Publication Suite
description: Learn how to conduct large-scale evaluations, aggregate results, and generate professional leaderboards.
---

The **Advanced Publication Suite** provides the professional-grade conductor logic required to execute large-scale agent benchmarking campaigns and generate publishable leaderboards.

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

---

## 🚀 Quick Start: Pilot Mode

Use **Pilot Mode** for rapid iteration, testing new scenarios, or verifying your agent integration. It runs 5 iterations across a 10-scenario subset.

### Example: Running a pilot
```bash
python scripts/publication_suite/publication_suite.py --mode pilot --agent-name "GPT-5.4-Mini-Pilot" --agent "http://localhost:5001/execute"
```
**Outcome:** Generates a `pilot_preview.html` and statistical summary in 3-5 minutes.

---

## ⚔️ Model Wars: Multi-Agent Benchmarking

The suite supports **Model Wars** mode, allowing you to benchmark multiple agents against the same scenario library in a single pass.

### 1. Define Agent Inventory
Provide an **Agent Inventory** YAML file (Default: `scripts/publication_suite/agents_inventory.yaml`).
```yaml
agents:
  - name: "GPT-5.4-Mini"
    protocol: "openai"
    agent: "https://api.openai.com/v1/chat/completions"
  
  - name: "Local-Llama4"
    protocol: "ollama"
    agent: "http://localhost:11434"
```

### 2. Run Comparative Benchmark
```bash
python scripts/publication_suite/publication_suite.py --mode pilot --compare scripts/publication_suite/agents_inventory.yaml
```

---

## 🧪 Deep Dive: Determinism & Seeds

Reproducibility is a cornerstone of industrial evaluation. The harness uses deterministic seeds to ensure that stochastic agent processes remain consistent across re-runs.

### How Seeds Work
1.  **Global Initialization**: Providing `--seed 12345` initializes Python's `random`, `numpy`, and `PYTHONHASHSEED`.
2.  **Deterministic Offsets**: For multi-run batches, the Conductor applies a unique but predictable offset: `Final Seed = Base Seed + Run Index`.
3.  **Reproducible Failures**: Every failed run includes the exact seed used. You can re-run a specific scenario with that exact seed to observe the identical failure trace.

---

## 🛠️ Advanced Execution Options

The suite offers granular control over the evaluation campaign:

- **Path Slicing**: Target specific verticals or difficulty tiers.
  ```bash
  python scripts/publication_suite/publication_suite.py --run-id <id>
  ```
- **Custom Protocols**: Support for `socket://`, `local://`, and `framework://` prefixes.
- **Parallel Scaling**: Utilize `--parallel <N>` to scale workers across multiple cores.

---

## Understanding Outputs

Every execution creates a unique batch directory in `results/batch_YYYYMMDD_HHMMSS/`.

- **`manifest.json`**: The "flight manifest" linking scenarios, seeds, and logs.
- **`run_XXX.jsonl`**: Individual Flight Recorder traces for every single run.
- **`aggregated_results.json`**: Statistical summary (pass@k, CI 95%, cost, taxonomy).
- **`leaderboard.html`**: Professional visual report.
- **`publication_artifact_bundle.zip`**: The signed, immutable package for regulatory submission.

:::important
Because this bundling logic is part of the **Zero-Touch Core**, it serves as an immutable "Source of Truth" for regulatory or public disclosures.
:::
