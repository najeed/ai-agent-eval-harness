# Agent Eval Specification (AES) v0.2

AES is a standardized format for defining portable and robust AI agent benchmarks. v0.2 adds **World Shim configuration**, **multi-agent topology**, and **complexity classification** to the v0.1 enterprise validation features.

## Core Principles
1. **Determinism**: Scenarios should be reproducible and verifiable.
2. **Portability**: The format is framework-agnostic (LangGraph, CrewAI, etc.).
3. **Structured Metrics**: Success is measured via standardized metrics, thresholds, and weights.
4. **Environment Isolation**: Lifecycle hooks manage environment-side dependencies.
5. **VFS-Aware Simulation**: World Shims provide stateful, safe environment simulation.

## Key Sections

### 1. Metadata
Details about the benchmark suite (name, author, difficulty, tags).

### 2. Environment & Infrastructure Hooks
Defines where the evaluation runs and manages external state.
- `simulator`: The environment name/version.
- `hooks`: `pre_eval` and `post_eval` shell commands for setup/cleanup.

### 3. Strongly Typed Agent Tools
Documents the toolset the agent is expected to use, including full JSON Schemas for parameters.
- `name`: Tool identifier.
- `description`: Human-readable purpose.
- `parameters`: JSON Schema for input validation.

### 4. Task Prompting
The core interaction instructions.
- `system_prompt`: Global agent instructions.
- `user_prompt`: The specific request or problem statement.

### 5. Ground Truth & State Assertions
Defines expected outcomes beyond just agent text responses.
- `expected_outcome`: Flat object for basic verification.
- `expected_state`: Assertions against environment databases or state stores (e.g., SQL check).

### 6. Evaluation & Success Criteria
Heuristics for determining task success.
- `success_criteria`: List of checks (e.g., `tool_called`, `output_contains`, `factual_reference`).

### 7. Parametric Metrics & Policy Constraints
- `metrics`: Configurable metrics with `params` (e.g., LLM model choice) and `weight`.
- `policies`: Global safety/PII constraints that must not be violated, with associated `severity`.

### 8. Reference Trajectory (Golden Path)
A list of expected events (agent response, tool call) that serves as a guide for alignment.

### 9. Mutations & Reporting
- `mutations`: Perturbations for robustness testing (e.g., "angry_user").
- `reporting`: Controls for run trace exports and `run.jsonl` emission.

### 10. World Shim Configuration (v0.2) ⭐
Declare which environment simulators to mount for this benchmark.
- `enabled_shims`: List of shim keys (e.g., `["database", "stripe", "security"]`).
- Omit to mount all 20 built-in shims by default.
- Valid keys: `git`, `api`, `database`, `slack`, `crm`, `email`, `calendar`, `jira`, `cloud`, `terminal`, `stripe`, `erp`, `browser`, `kb`, `support`, `social`, `vector`, `cicd`, `iot`, `security`
- See [`07_WORLD_SHIMS_REFERENCE.md`](../docs/guides/help/07_WORLD_SHIMS_REFERENCE.md) for per-shim config.

### 11. Multi-Agent Topology (v0.2) ⭐
Define state access permissions for multi-agent crews.
- `agent_topology`: Map of agent names to `reads` and `writes` state path namespaces.

### 12. Complexity Level (v0.2) ⭐
- `complexity_level`: `low`, `medium`, or `high` — aligns with `scenario.schema.json`.

## Validation
```bash
eval-harness aes validate --path my_benchmark.aes.yaml
```

## Changelog
| Version | Changes |
|---|---|
| v0.2 | Added `enabled_shims`, `agent_topology`, `complexity_level` |
| v0.1 | Initial release: typed tools, hooks, state assertions, metrics, policies |
