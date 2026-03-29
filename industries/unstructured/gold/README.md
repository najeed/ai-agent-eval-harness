# Gold Standard: UNSTRUCTURED

This directory contains the **Regulatory-Grade** autonomous agent scenarios for the unstructured sector, strictly adhering to the **AES v1.2 Regulatory Enforcement Layer** specification.

##  Verification OS Compliance
- **State-Machine DAG**: All scenarios implement a non-linear `workflow` with explicit `nodes` and `edges`, ensuring deterministic state transitions and dependency gating.
- **Typed Outcomes (Standards Registry)**: Scenarios are mapped to the industrial standards registry (NIST/Industrial Best Practices).
- **Pluralistic Judging (IJA)**: Outcomes are verified using a consensus panel. This industry mandates an Inter-Judge Agreement (IJA) threshold of `0.85` for non-repudiable audit logs.

##  Scenario Holarchy
Scenarios in this directory are structured as deterministic state-transition maps, verifying the agent's ability to navigate complex industrial protocols without state-divergence.

## 🧪 Execution
To run the gold standard evaluation for this industry:
```bash
multiagent-eval evaluate --path industries/unstructured/gold --attempts 3 --ija-threshold 0.85
```
