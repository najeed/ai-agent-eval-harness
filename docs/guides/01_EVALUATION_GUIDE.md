<!-- docs/guides/01_EVALUATION_GUIDE.md -->

# Evaluation Guide

This guide explains the philosophy behind our evaluation scenarios and how to interpret them.

## The Scenario Corpus

The harness ships with a production-grade corpus of **5,000+ scenarios** across 45+ industries. This includes specialized high-stakes categories:
- **Cross-Industry**: Inter-sector policy negotiation.
- **Ethical Guardrails**: Hardened safety and PII tests.
- **Interactive Complexity**: Multi-turn flows with HITL.
- **Simulations**: High-fidelity lab environments.

## Scenario Structure

Each evaluation is defined by a `.json` file in an industry's `scenarios` directory. The file has the following top-level keys:

-   `scenario_id`: A unique identifier for the scenario (e.g., `telecom-cs-001`).
-   `title`: A human-readable title.
-   `description`: A brief explanation of the overall goal of the scenario.
-   `use_case`: The specific business function being tested (e.g., `Customer Service`).
-   `industry`: The industry this scenario belongs to.
-   `core_function`: The category within the use case this scenario belongs to.
-   `dataset`: (Optional) Path and format of a synthetic or real dataset required for this scenario. **Supports Path Decoupling (v1.1+)**: Relative paths (e.g., `./data.csv`) are resolved relative to the scenario file itself, allowing for portable scenario bundles.
-   `initial_state`: (Optional) The starting state for the sandbox. Supports nested dictionaries with dot-notation verification.
-   `policies`: (Optional) Governance rules to enforce during execution.
-   `tasks`: An array of task objects that represent the steps an agent must take.

## Task Structure

Each object in the `tasks` array represents a single step and contains:

-   `task_id`: A unique ID for the task within the scenario (e.g., `task-1`).
-   `description`: A clear description of what the agent needs to accomplish.
-   `expected_outcome`: A description of what a successful completion of the task looks like.
-   `required_tools`: A list of tool/API names that the agent is expected to use for this task.
-   `expected_state_changes`: (Optional) A list of state paths and values that should be true after the task.
-   `success_criteria`: An array defining how to measure success.

### LLM-as-Judge & Rubrics
For semantic or safety-critical evaluations, you can use the `luna_judge_score` metric. This metric can be customized using a `judge_config` object within the criterion:

- **`judge_rubric`**: Select a specialized rubric (e.g., `clinical_safety`, `fiduciary_accuracy`, `policy_adherence`).
- **`judge_provider`**: Override the global judge model (e.g., `openai`, `gemini`).
- **`required`: Setting this to `true` (v1.1+)** ensures that if the judge fails to initialize (e.g., missing API key), the evaluation terminates immediately with a clear error rather than falling back to weak heuristics.

A task is only considered successful if **all** of its success criteria are met.

## State Verification
The `state_verification` metric now supports **dot-notation** for inspecting nested objects in the sandbox state.
- **Example**: A path of `user.profile.balance` will correctly navigate through nested dictionaries in the `actual_state` to verify the final value.

## Advanced Orchestration

- **HITL (Human-In-The-Loop)**: Pause evaluations for manual intervention via the `human` adapter.

## Visual Evaluation & Debugging (Admin Console)

Beyond the CLI, the harness provides a **Unified React SPA** Admin Console for visual management:
- **Scenario Explorer**: Browse the catalog with faceted filters and global search.
- **Visual AES Builder**: Drag-and-drop integrated logic builder for complex flows.
- **Reports & Traces**: Historical execution timeline with detailed analysis, discovered Agent Identity (names/models), and instant "View Report" navigation.
- **Visual Debugger**: Real-time trajectory playback with interactive state inspection, human-readable agent labels, and trace export.

Launch with:
```bash
eval-harness console
```


## Available Metrics

| Metric | Function | Description |
|---|---|---|
| `tool_call_correctness` | `calculate_tool_call_correctness` | Exact set-match of expected vs. actual tools |
| `state_verification` | `calculate_state_correctness` | Verify persistent system state changes |
| `policy_compliance` | `calculate_policy_compliance` | Detect governance policy violations |
| `delegation_latency` | `calculate_delegation_latency` | Measures the 'Thinking Cost' of handoffs |
| `delegation_loop_risk` | `calculate_delegation_loop_risk` | Detects 'Infinite Re-planning' cycles |
| `consensus_scoring` | `calculate_consensus_scoring` | Semantic similarity judge for agent agreement |
| `communication_clarity` | `calculate_communication_clarity` | Checks summary length and semantic quality |
| `factual_accuracy` | `calculate_factual_accuracy` | LLM-based verification of agent's final answer |
| `performance_efficiency` | `calculate_efficiency` | Weighted score of turns taken vs. goal reached |
| `security_guardrail` | `calculate_guardrail_violation` | Detection of prompt injection or sensitive data leaks |

## Community Benchmarks

Instead of relying solely on local `.json` or `.aes.yaml` files, the `eval-harness` can now pull and format datasets from major community benchmarks on-the-fly using URIs.

```bash
# Load the 2023 GAIA validation set
eval-harness evaluate --path gaia://test_2023

# Load AssistantBench tasks
eval-harness evaluate --path assistantbench://dev
```
The universal loader will dynamically download these datasets, wrap them in compatible `Scenario` objects, and apply the correct specific evaluation metrics.

## Multi-Agent Scenario Schema

Scenarios now support complex topologies. Example snippet:

```json
{
  "version": "2.0.0",
  "agent_topology": {
    "agent_1": { "writes": ["ns1"], "reads": ["ns2"] }
  }
}
```

## Schema Validation

Scenarios are validated against `schemas/scenario.schema.json` at load time. Any scenario that fails validation will raise a `ValueError` with a clear error message.
