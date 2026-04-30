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

-   `aes_version`: (String) The Agent Eval Standard version (e.g., `1.4`).
-   `metadata`: (Required) The authoritative identity vault for the scenario.
    -   `id`: (Required) Global unique forensic identifier.
    -   `name`: (Required) Human-readable title of the scenario.
    -   `description`: (Required) Brief explanation of the evaluation goal.
    -   `compliance_level`: (Required) Regulatory tier (`Standard`, `Gold`, `Regulatory_Audit`).
    -   `industry`: The targeted sector (e.g., `finance`).
    -   `core_function`: The specific business category being tested.
    -   `capabilities`: (Recommended) List of required infrastructure skills (v1.4+).
-   `dataset`: (Optional) Path and format of a dataset required for this scenario. **Supports Path Decoupling (v1.1+)**: Relative paths are resolved relative to the scenario file itself.
-   `initial_state`: (Optional) Seed state for the sandbox (World Genesis).
-   `workflow`: (Required) The DAG defining the execution trajectory.
    -   `nodes`: Array of task objects.
    -   `edges`: Dependency mappings between tasks.

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
- **Connection Protocols**: The harness supports three primary communication modes:
    - **HTTP**: Standard REST/JSON endpoint.
    - **Local**: Executes a subprocess and communicates via stdin/stdout. Configuration: `AGENT_LOCAL_CMD`.
    - **Socket**: Connects to a raw TCP socket. Configuration: `AGENT_SOCKET_ADDR`.

## Visual Evaluation & Debugging (**Visual Debugger**)

Beyond the CLI, the harness provides a **Unified React SPA** Visual Debugger for visual management:
- **Scenario Explorer**: Browse the catalog with faceted filters and global search.
- **Visual AES Builder**: Drag-and-drop integrated logic builder for complex flows.
- **Reports & Traces**: Historical execution timeline with detailed analysis, discovered Agent Identity (names/models), and instant "View Report" navigation.
- **Visual Debugger**: Real-time trajectory playback with interactive state inspection, human-readable agent labels, and trace export.

Launch with:
```bash
agentv console
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

## Extensible Metric Dispatch (v1.6.0)

The AgentV v1.6.0 engine uses a **Zero-Touch** dynamic dispatch system for metrics. Instead of hardcoded mappings, metrics "request" the data they need by naming parameters in their function signature.

### How it works
When the engine evaluates a metric, it introspects the function's signature and automatically fulfills its arguments from the session's **Context Map**.

### Available Context Parameters
You can use any of the following parameter names in your metric functions:

| Parameter Name | Description |
| :--- | :--- |
| `eval_context` | The full configuration dictionary for the current metric criterion. |
| `agent_summary` | The sanitized text summary provided by the agent. |
| `history` | The full conversation history list. |
| `actual_state` | The current state of the Tool Sandbox (World State). |
| `used_tools` | List of tool names used during the task. |
| `expected_tools` | List of tools the agent was required to use. |
| `expected` | The primary goal/outcome expected for the task. |
| `actual` | Alias for `agent_summary`. |
| `agent_sequence` | List of identifiers for agents involved in the session. |
| `turns_taken` | Number of turns consumed by the agent. |
| `max_turns` | The maximum turns allowed for the task. |
| `attempt_number` | The current evaluation attempt (1-indexed). |
| `metadata` | The full scenario metadata (Industry, Compliance Level). |
| `action_trace` | Granular record of all tool calls and timestamps. |
| `session_metadata` | **[System]** Infrastructure details (Protocols, Endpoints). |
| `forensic_telemetry` | **[System]** Resource usage (CPU, RAM). |

### Example
```python
def my_custom_metric(actual_state, used_tools, eval_context):
    # Logic to verify state and tools...
    return 1.0
```

### Metric Security & Extension Trust
To protect sensitive infrastructure data, the engine enforces a **Trust Boundary** for metrics:

1.  **Standard Parameters**: (Summary, History, Metadata) are available to all metrics.
2.  **System Parameters**: (`session_metadata`, `forensic_telemetry`) are only available to **Trusted Extensions**.
3.  **Isolation**: Mutable data like `history` and `actual_state` are passed as **Deep Copies** to non-core metrics to prevent accidental or malicious state mutation during evaluation.

To grant an extension "Trusted" status, set `"trusted": true` in the plugin or shim registry entry. This also enables zero-copy access to mutable data, improving performance for large datasets.

## Community Benchmarks

Instead of relying solely on local `.json` or `.aes.yaml` files, the `agentv` can now pull and format datasets from major community benchmarks on-the-fly using URIs.

```bash
# Load the 2023 GAIA validation set
agentv evaluate --run-id <id>

# Load AssistantBench tasks
agentv evaluate --run-id <id>
```
The universal loader will dynamically download these datasets, wrap them in compatible `Scenario` objects, and apply the correct specific evaluation metrics.

## Multi-Agent Scenario Schema

Scenarios now support complex topologies. Example snippet:

```json
{
  "aes_version": 1.4,
  "metadata": {
    "id": "multi_agent_flow_01",
    "name": "Collaborative Financial Audit",
    "compliance_level": "Gold",
    "agent_topology": {
      "agent_1": { "writes": ["ns1"], "reads": ["ns2"] }
    }
  },
  "workflow": {
    "nodes": [],
    "edges": []
  }
}
```

## Schema Validation

Scenarios are validated against `schemas/scenario.schema.json` at load time. Any scenario that fails validation will raise a `ValueError` with a clear error message.
