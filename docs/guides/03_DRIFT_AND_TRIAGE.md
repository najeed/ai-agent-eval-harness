# Guide: Drift Management & Edge-Case Triage

This guide details how to use the Semantic Bridge features to ingest real-world behavior and analyze agent failures.

## 1. Drift Importer (`import-drift`)

The Drift Importer allows you to convert production traces (agent/user interaction logs) into reusable evaluation scenarios. This is critical for building regression suites from real-world "drift."

### Usage
```bash
eval-harness import-drift --input path/to/trace.json --industry telecom
```

### Trace Format
The importer expects a list of interaction objects:
```json
[
  {"role": "user", "content": "I need help with my bill."},
  {"role": "assistant", "content": "I can help with that. What is your account number?"}
]
```

### Result
A new v2 scenario file is created in `industries/[industry]/scenarios/drift-[hash].json`, containing the original history as `ground_truth_history`.

---

## 2. Edge-Case Triage Library

The Triage Engine automatically analyzes failed evaluation tasks and applies tags based on known failure patterns.

### Built-in Triage Tags
| Tag | Description |
| :--- | :--- |
| `CONNECTION_ERROR` | Agent communication failed (e.g., timeout, 500 reset). |
| `POLICY_VIOLATION` | The agent attempted an action forbidden by the `ToolSandbox` policies. |
| `TOOL_ERROR` | A mock tool returned an error status during execution. |
| `STALL` | The agent hit the maximum number of turns without reaching a final answer. |

### How it Works
The Triage Engine inspects the `conversation_history` and `EvaluationContext` after a run to match heuristics.

### Example Console Output
```text
Task: refund_processing [FAILURE [CONNECTION_ERROR]]
  FAILED Metric: generic_accuracy | Score: 0.00 | Threshold: 0.80
```
