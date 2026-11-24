---
title: "Agent Evaluation Specification (AES v1.4)"
description: "Authoritative specification for the AES v1.4 schema contract, workflow DAG, evaluation criteria, and environment sandbox plumbing."
---

AES scenarios are validated against [the root schema](/spec/aes/aes.schema.json)
and its metadata, workflow and evaluation definitions. Use these files as the
field authority rather than a separate handwritten schema copy.

## Required structure

The root requires numeric `aes_version: 1.4`, `metadata`, `workflow`, and
`evaluation`. Unknown root fields are rejected. Metadata requires `name`, `id`
and `compliance_level`; supported levels are `Standard`, `Gold`, and
`Regulatory_Audit`. `capabilities`, `industry` and `standards_registry` are
optional metadata. Standard identifiers must come from the schema enum, such as
`NIST_AI_RMF`, `ISO_20022` or `HIPAA`.

```json
{
  "aes_version": 1.4,
  "metadata": {
    "id": "loan-assessment-example",
    "name": "Loan assessment example",
    "compliance_level": "Standard",
    "capabilities": ["tool_use"],
    "standards_registry": ["NIST_AI_RMF"]
  },
  "workflow": {
    "nodes": [{
      "id": "assess",
      "task_description": "Return STATUS: APPROVED after checking the supplied policy.",
      "success_criteria": [{"metric": "generic_accuracy", "threshold": 1.0}],
      "expected_outcome": [{"target": "message", "expected": "STATUS: APPROVED", "mode": "exact"}]
    }],
    "edges": []
  },
  "evaluation": {}
}
```

## Nodes, assertions and evaluation

Workflow requires `nodes` and `edges`. The schema requires `id` and
`task_description` on each node. Declare meaningful `success_criteria` and
`expected_outcome` assertions for evaluable evidence; schema validity alone does
not establish adequate coverage or certifiability.

`success_criteria` entries require a registered metric name and a threshold.
Discover installed metrics with `agentv list-metrics`. Built-in names include
`generic_accuracy`, `tool_call_correctness`, `policy_compliance`,
`state_verification`, and `luna_judge_score`. An unknown metric produces an invalid
evaluation, not a passing result.

`expected_outcome` is an array. The workflow schema accepts `exact`, `regex`, and
`numerical_tolerance` modes. These assertion modes are separate from metric
registry names; do not use `regex`, `exact_match`, `json_schema`, or
`tool_call_parameter` as built-in metric names. State assertions should declare
the target/property and bounded state projection needed to observe their result.

The evaluation definition supports a `consensus` object with `strategy`,
`min_judges`, optional `judge_panel`, and `ija_threshold` at evaluation level.
Strategies are `Majority_Vote`, `Weighted_Average`, and `Absolute_Unanimity`.

## Routing and environment

Put required capabilities in `metadata.capabilities`. Configure an agent through
`metadata.agent.protocol` / `metadata.agent.endpoint`, capability routing, or
explicit CLI/runtime configuration. Root `agent_url` and `temperature` are not
AES fields.

Optional root fields include `tools`, `initial_state`, `environmental_snapshot`,
`enabled_shims`, `failure_policy`, `cleanup_workspace`, `description`, `industry`,
and `use_case`. `failure_policy` is one of `fail_fast`, `continue_independent`,
`compensate_then_fail`, or `best_effort`.

Shim activation follows the [discovery policy](/evaluator/discovery/). Sandbox
workspaces default to `workspace/<run_id>` and are retained unless cleanup is
explicitly enabled. Keys/configuration, sandbox state and provider-owned evidence
have separate lifecycles. The run provider owns exact committed trace bytes,
execution manifests, lifecycle state and certificate publication.

## Validation and execution

```bash
agentv aes validate --path industries/finance/scenarios/loan_approval_risk_check.json
agentv lint --path industries/finance/scenarios/loan_approval_risk_check.json
```

JSON and YAML scenario files can be loaded by the runtime. Use a file or catalog
ID with `run` and a dataset/directory with `evaluate`. Certification remains a
separate operation requiring eligible execution, signer and oracle evidence.
