---
title: 3D Mutation Engine & Algebraic Combinators
description: Mathematical foundations, coordinate taxonomy, composable combinators, and deterministic execution for adversarial agent evaluation.
---

Mutations have a formal coordinate `(vector, operation, tier)` and a separate
delivery capability. A descriptor or generated variant does not prove that a
fault executed against a runtime boundary.

## Coordinate vocabulary

`agentv_runtime.contracts.MutationVector` defines fourteen values: input, context,
memory, retrieval, tool, state, identity, authorization, policy, objective, time,
concurrency, dependency and multi_agent. Operations include insert, delete,
replace, corrupt, delay, reorder, duplicate, replay, drop, conflict, escalate,
expire and drift. Tiers range from T0_linguistic to T5_enterprise.

The coordinate vocabulary is larger than the set of implemented Core delivery
providers. Inspect the installed mutation catalog and its capability metadata
before selecting an operation. In particular, Core concurrent delivery and
duplicate_commit are unsupported; they must not be reported as delivered faults.

## Contracts and combinators

```python
from agentv_runtime.contracts import (
    MutationContext, MutationCoordinate, MutationDescriptor,
    MutationHandle, MutationOperation, MutationTier, MutationVector,
)
from eval_runner.mutations.mutator import (
    ScenarioMutator, sequence, repeat, probability,
    after_event, before_commit, between_steps,
)
```

For existing mutator instances, supported factory calls are:

```python
pipeline = sequence(mutator_a, mutator_b)
repeated = repeat(mutator_a, count=3)
sampled = probability(mutator_a, p=0.25)
after_tool = after_event(mutator_b, "tool_result")
at_commit = before_commit(mutator_b)
in_window = between_steps(mutator_a, min_step=3, max_step=6)
```

These examples assume compatible instantiated mutators. `sequence` is variadic,
not a list-taking factory. Timing predicates require the mutator as their first
argument. `concurrent()` creates a reserved combinator whose delivery raises
`UnsupportedMutationError`; it does not run or merge simulated races.

`MutationDescriptor` uses id, label, vector, operation, tier, source, description,
target_field, regulatory_frameworks, org_id, deterministic and parameters_schema.
Use the current class rather than an older name/provenance/category schema copy.

## Scenario generation versus delivery

```bash
agentv mutate --input baseline.json --type injection --output adversarial.json
```

Create the baseline first. The command writes a separate variant and reports
the in-memory lint assessment. `POST /api/v1/mutate` returns
`operation: "scenario_generation"` and `delivery_status: "NOT_EXECUTED"`.
It does not execute the fault. Runtime execution uses SessionManager,
WorkflowInterpreter and installed mutation delivery providers; there is no
`agentv eval` command or `SyntheticService.generate_variants` public API.

Keep scenarios serializable and declarative. Custom runtime providers/plugins
implement executable behavior outside scenario data. Root AES constraints and
failure_policy enums still apply to generated variants. A lint tier is a quality
assessment, not a certificate: GOLD >=90, SILVER >=70, BRONZE >=50, otherwise
UNRANKED.

## Reproducibility and lineage

Runner attempts use `base_seed + (attempt - 1)`. MutationContext supplies its RNG
for probabilistic combinators. There is no universal hash(master,scenario,step)
sub-seed formula in this API. Seeds alone do not freeze remote model behavior or
external service state.

Preserve parent scenario identity and mutation metadata in valid metadata fields.
Executed fault evidence must be delivered and acknowledged at the relevant tool,
commit, approval or state boundary. Generation metadata alone is not execution
evidence. The scoped provider owns mutation events and exact trace bytes, which
must reconcile with signed finalization and certification evidence.

Catalog HTTP requests derive organizational scope from authenticated runtime
context; query tenant labels are not authorization. Programmatic providers use
`MutationService.list_mutation_catalog` within the application's trusted scope.
