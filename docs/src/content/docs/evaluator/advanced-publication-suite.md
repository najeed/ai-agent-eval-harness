---
title: Advanced Publication Suite
description: Learn how to conduct large-scale evaluations, aggregate results, and generate professional leaderboards.
---

The publication suite conducts local scenario campaigns, aggregates results,
renders HTML and asks the artifact plugin to bundle selected outputs.

## Run a pilot

```bash
python eval_runner/publication_suite/publication_suite.py --mode pilot --path industries/finance/scenarios --agent-name MyAgent --agent http://localhost:5001/execute_task
```

The conductor selects immediate `*.json` children of `--path`, not recursively
nested scenarios. Pilot mode performs five runs per selected scenario, serially;
it does not select an automatic ten-scenario subset. Standard conductor execution
defaults to ten runs per scenario and uses worker processes.

## Configuration and arguments

The wrapper accepts `--mode`, `--path`, `--agent-name`, `--protocol`, `--agent`,
`--compare`, `--parallel`, `--batch-id`, and `--output-dir`. It does not accept
`--run-id` or `--seed`. `eval_runner/publication_suite/config.yaml` contains
illustrative settings; the wrapper/conductor do not load it to control run counts
or worker arguments.

To select run counts and seeds directly, invoke the conductor:

```bash
python eval_runner/publication_suite/conductor.py --path industries/finance/scenarios --runs 10 --seed 42 --parallel 4
```

The conductor derives seeds from the base and task index and starts subprocesses
with `PYTHONHASHSEED`. Remote model determinism still depends on the provider and
environment; equal seeds do not guarantee identical reasoning trajectories.

## Compare agents

Create a user-owned inventory file:

```yaml
agents:
  - name: AgentA
    protocol: http
    agent: http://localhost:5001/execute_task
  - name: AgentB
    protocol: http
    agent: http://localhost:5002/execute_task
```

```bash
python eval_runner/publication_suite/publication_suite.py --mode pilot --path industries/finance/scenarios --compare agents_inventory.yaml
```

## Outputs and evidence

Default batches are written under `results/batch_<timestamp>/`. Use `--batch-id`
or `--output-dir` to choose a destination. The suite produces `manifest.json`,
`aggregated_results.json`, and `leaderboard.html` or `pilot_preview.html`.

The bundler requires an active `ArtifactPlugin` and includes selected batch
reports/manifest files. Inspect the actual bundle and evidence ledger before
sharing; creating a ZIP does not certify execution. Use the
[artifact guide](/scholar/publishing/artifact-bundles/) for verification inputs.
