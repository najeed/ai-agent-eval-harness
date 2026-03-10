# CLI Reference

The `eval-harness` (or `python -m eval_runner`) CLI provides a comprehensive suite of tools for agent evaluation, management, and debugging.

## Core Commands

### `evaluate`
Run evaluations on one or more scenarios.
```bash
eval-harness evaluate --path <path> [--attempts K] [--limit N] [--verbose]
```
- `--path`: Path to a JSON scenario file or a directory containing scenarios.
- `--attempts`: Number of attempts per scenario (for pass@k and consistency metrics).
- `--limit`: Max number of scenarios to run.
- `--format`: Dataset format (`jsonl` or `csv`).

### `run`
Execute a single scenario file.
```bash
eval-harness run --scenario <path>
```

## Specification & Validation

### `aes validate`
Validate Agent Eval Specification (.aes.yaml) files against the official schema.
```bash
eval-harness aes validate <path>
```

### `spec-to-eval`
Convert a Markdown PRD/Spec file into a structured Scenario JSON.
```bash
eval-harness spec-to-eval --input <prd.md> [--output <scenario.json>]
```

## Drift & Research

### `import-drift`
Convert production traces (interaction logs) into reusable evaluation scenarios.
```bash
eval-harness import-drift --input <trace.json> --industry <industry>
```

### `mutate`
Generate adversarial variants of a scenario (e.g., adding typos, prompt injection).
```bash
eval-harness mutate --input <scenario.json> --type <mutation_type>
```

## Debugging & Exploration

### `replay`
Re-execute a `run.jsonl` flight recorder log to debug "wrong turns".
```bash
eval-harness replay <path/to/run.jsonl>
```

### `playground`
Launch an interactive REPL to talk to an agent directly in the terminal.
```bash
eval-harness playground [--agent <url>]
```

### `record`
Record a live interaction with an agent and save it as a structured trace.
```bash
eval-harness record [--agent <url>]
```

## Utilities

### `doctor`
Check the local environment for missing dependencies or configuration issues.
```bash
eval-harness doctor
```

### `quickstart`
Run a 60-second guided demo that spawns a mock agent and executes an evaluation.
```bash
eval-harness quickstart
```

### `report`
Generate a standalone HTML report from a execution trace.
```bash
eval-harness report <path/to/run.jsonl>
```

### `scenario generate`
Interactively workspace to generate new test scenarios via a terminal wizard.
```bash
eval-harness scenario generate
```
