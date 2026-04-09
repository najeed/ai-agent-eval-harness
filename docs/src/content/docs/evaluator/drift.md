---
title: Drift Management & Edge-Case Triage
description: Ingest real-world behavior and analyze agent failures using the Triage Engine.
---

Industrial agent evaluation requires more than static datasets; it needs the ability to learn from real-world production "drift" and systematically classify why agents fail.

## 🔄 Behavioral Drift Importers

The **Drift Importer** (`import-drift`) allows you to convert production interaction logs into reusable evaluation scenarios. This enables the creation of a "regression suite" from actual edge cases encountered in the field.

### Usage
```bash
multiagent-eval import-drift --input path/to/trace.json --industry telecom
```

### Trace Format
The engine expects standard role-based interaction objects:
```json
[
  {"role": "user", "content": "I need help with my bill."},
  {"role": "assistant", "content": "I can help with that. What is your account number?"}
]
```

### Automated Scenario Generation
Upon import, the engine generates a new **AES v1.4** scenario file in `industries/[industry]/scenarios/drift-[hash].json`. The original conversation is stored as `ground_truth_history` for N-shot comparison.

---

## 🔍 Edge-Case Triage Library

The **Triage Engine** automatically inspects failed tasks and applies diagnostic tags based on the [Failure Taxonomy](/ai-agent-eval-harness/evaluator/taxonomy/).

### Industrial Triage Tags
| Tag | Description |
| :--- | :--- |
| **`CONNECTION_ERROR`** | Communication failure with the agent or LLM provider (e.g., 500 reset). |
| **`POLICY_VIOLATION`** | The agent attempted an action forbidden by the [Secure Sandbox](/ai-agent-eval-harness/auditor/trust-protocol/). |
| **`TOOL_ERROR`** | A World Shim returned an error status during tool execution. |
| **`STALL`** | The agent hit the turn limit without reaching a terminal `final_answer`. |

### How It Works
After each run, the engine executes a heuristic pass over the trajectory.
```bash
Task: refund_processing [FAILURE [CONNECTION_ERROR]]
  FAILED Metric: generic_accuracy | Score: 0.00 | Threshold: 0.80
```

---

## 🧪 Forensic Diagnostics (`explain`)

While triage provides categorical tags, the `explain` command performs a deep forensic analysis of the execution trace to identify root causes.

### Usage
```bash
multiagent-eval explain --path runs/run.jsonl
```

### Forensic Features
- **Tiered Confidence Scoring**: Distinguishes between explicit violations (100%), induced system errors (85%), and heuristic fallbacks (50%).
- **Remediation Advice**: Provides targeted prompts for refinement (e.g., "Refine sandbox policy for `read_file` to allow restricted access").
- **Pinpoint Divergence**: Identifies the exact turn index where the agent's logic diverged from the [Trust Protocol](/ai-agent-eval-harness/auditor/trust-protocol/).

> [!TIP]
> **Visual Triage**: Failure tags are integrated into the [Integrated Console](/ai-agent-eval-harness/extender/api-reference/). High-priority tags like `POLICY_VIOLATION` are highlighted in the trajectory timeline for manual review.
