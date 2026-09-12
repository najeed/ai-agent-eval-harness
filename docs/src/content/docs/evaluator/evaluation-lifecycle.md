---
title: "Evaluation Execution Lifecycle & Metric Aggregation"
description: "Evaluator guide to evaluation phases, deterministic multi-attempt seeding, Pass@K statistics, and node verdict scoring."
---

# Evaluation Execution Lifecycle & Metric Aggregation

For industry domain experts and evaluators, AgentV provides an auditable, statistically rigorous evaluation pipeline. This guide explains how macro evaluation phases progress from initial scenario seeding to multi-attempt Pass@K aggregation.

---

## 1. Macro Evaluation Flow

```
[ Session Initialization ]
       │  run_start (captures scenario definition & truth level)
       │  strategy_start (pass_at_k exploration)
       │  phase_start (pass_at_k_execution)
       ▼
┌─────────────────────────────────────────────────────────┐
│ Attempt Loop (k = 1 .. attempts)                        │
│ - Seeding: Seed_k = Base_Seed + (k - 1)                 │
│ - Execution IR DAG traversal                            │
│ - Maneuver execution & turn interactions                │
│ - Transition state parity verification                  │
│ - Node-level oracle evaluations                         │
└──────────────────────────┬──────────────────────────────┘
                           ▼
[ Evaluation Wrap-Up ]
       │  phase_end (pass_at_k_execution)
       │  Pass@K unbiased statistical computation
       │  strategy_end (status="success" | "failure")
       │  run_end (authoritative terminal event + finalization)
```

---

## 2. Deterministic Seeding & Pass@K Statistics

### Reproducible Seeding
To eliminate variance across runs while ensuring statistical independence between repeated attempts, AgentV derives attempt seeds deterministically:

$$\text{Seed}_k = \text{Seed}_{\text{base}} + (k - 1)$$

For example, given base seed `1000` and $k=3$, the harness executes attempts with seeds `1000`, `1001`, and `1002`.

### Standardized Statistical Aggregation
At `phase_end`, the harness computes standardized statistics over executed attempts:

1. **Pass@K Unbiased Estimator**:
   $$\text{pass\_at\_k} = 1 - \frac{\binom{n - c}{k}}{\binom{n}{k}}$$
   *(where $n$ is total executed attempts and $c$ is successful attempts).*

2. **Attempt Success Rate**:
   Raw proportion of successful attempts ($c / n$).

3. **Conjunctive vs. Disjunctive Evaluation**:
   - `all_pass`: Boolean indicating every attempt succeeded ($c = n$). Crucial for high-assurance compliance.
   - `any_pass`: Boolean indicating at least one attempt succeeded ($c \ge 1$).

---

## 3. Node Verdict & State Parity Scoring

Agent success is never determined by conversational completion alone. At the conclusion of each tactical node (`maneuver_end`), AgentV evaluates three independent verification layers:

1. **Assertion Oracles (`metrics_calculator`)**:
   Evaluates rubric metrics (e.g. `luna_judge_score`, semantic similarity, schema accuracy). Oracles produce typed outcomes: `PASS`, `FAIL`, `INVALID`, or `NOT_APPLICABLE`.
2. **Transition-Based State Parity**:
   Compares sandbox world state before and after node execution. Computes `state_before_hash` and `state_after_hash` (FIPS 202 SHA3-256) to ensure state transitions match the declared contract.
3. **Policy Decisions**:
   Inspects all policy evaluations taken during the node. Any unauthorized tool call or policy denial overrides conversational results and forces a `POLICY_DENIED` failure.

---

## 4. Execution Truth Accountability

When evaluating agents, the validity of the benchmark depends on the execution environment:

- **`live`**: Real external APIs and production models. Certificates are authoritative.
- **`hybrid`**: Mix of live model inference and sandboxed local services. Certificates are authoritative.
- **`simulated`**: Mocked environment responses. Traces are automatically stamped `provisional: true`.

> [!WARNING]
> Evaluation results from `simulated` mode cannot be cited as proof of real-world compliance.
