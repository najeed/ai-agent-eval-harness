---
title: 3D Mutation Engine & Algebraic Combinators
description: Mathematical foundations, coordinate taxonomy, composable combinators, and deterministic execution for adversarial agent evaluation.
---

The **AgentV 3D Mutation Engine** provides an industrial-grade, algebraically composable framework for perturbing scenarios and injecting deterministic in-run adversarial stress. Rather than treating adversarial testing as ad-hoc prompt variations, AgentV models mutations across a formal **3-Dimensional Coordinate Space** ($V \times O \times T$) and provides first-class algebraic combinators for sequencing, branching, and synchronizing runtime perturbations.

```
                  Mutation Vectors (V)
                     [13 Dimensions]
                            ▲
                            │
                            │        ● MutationCoordinate(V, O, T)
                            │
                            └────────────────────────► Mutation Operations (O)
                           /                            [13 Operators]
                          /
                         /
                        ▼
               Mutation Tiers (T)
                 [6 Risk Tiers]
```

---

## 1. 📐 The 3D Coordinate Space

Every mutation in AgentV is formally indexed by a `MutationCoordinate(vector, operation, tier)`.

### Dimension 1: Target Vectors (`MutationVector`)
Specifies the exact subsystem or layer targeted by the mutation:

| Vector | Identifier | Description |
| :--- | :--- | :--- |
| `INPUT` | `input` | User instructions, raw prompts, task descriptions, and initial inputs. |
| `CONTEXT` | `context` | In-context conversation history, system instructions, and persona definitions. |
| `MEMORY` | `memory` | Long-term memory store, scratchpads, and persistent key-value states. |
| `RETRIEVAL` | `retrieval` | RAG documents, search indices, vector database chunking, and ranking. |
| `TOOL` | `tool` | Tool declarations, function schemas, parameters, and invocation return payloads. |
| `STATE` | `state` | Environment and sandbox world state (VFS, databases, registries). |
| `IDENTITY` | `identity` | Agent/user identity claims, session tokens, and tenant markers. |
| `AUTHORIZATION` | `authorization` | Scopes, permissions, capability tokens, and RBAC barriers. |
| `POLICY` | `policy` | Safety rules, organizational constraints, and regulatory policies. |
| `TIME` | `time` | Clocks, timestamps, timeouts, latency budgets, and durations. |
| `CONCURRENCY` | `concurrency` | Parallel tasks, race conditions, shared resources, and lock interleavings. |
| `DEPENDENCY` | `dependency` | Upstream service dependencies, external APIs, and network hops. |
| `MULTI_AGENT` | `multi_agent` | Inter-agent communication messages, handoffs, and consensus protocols. |

### Dimension 2: Operations (`MutationOperation`)
Specifies the transformational action applied to the target vector:

| Operation | Identifier | Semantics |
| :--- | :--- | :--- |
| `INSERT` | `insert` | Injects synthetic content, unexpected tokens, or unauthorized instructions. |
| `DELETE` | `delete` | Removes critical fields, constraints, headers, or state attributes. |
| `REPLACE` | `replace` | Substitutes values with conflicting, stale, or malformed data. |
| `CORRUPT` | `corrupt` | Introduces typographical noise, bit-rot, truncation, or encoding errors. |
| `DELAY` | `delay` | Injects synthetic latency, clock drift, or execution timeouts. |
| `REORDER` | `reorder` | Permutes sequence of messages, tool outputs, or pipeline stages. |
| `DUPLICATE` | `duplicate` | Repeats tool calls, idempotency keys, or conversation utterances. |
| `REPLAY` | `replay` | Replays stale authentication tokens or previously completed messages. |
| `DROP` | `drop` | Silently discards events, tool acknowledgments, or state updates. |
| `CONFLICT` | `conflict` | Creates conflicting concurrent writes or contradictory instructions. |
| `ESCALATE` | `escalate` | Injects privilege escalation vectors or forged administrative tokens. |
| `EXPIRE` | `expire` | Prematurely invalidates sessions, leases, or cache entries. |
| `DRIFT` | `drift` | Applies semantic schema drift, gradual topic drift, or API version divergence. |

### Dimension 3: Calibration Tiers (`MutationTier`)
Calibrates the blast radius, behavioral depth, and operational risk of the mutation:

| Tier | Enum | Scope | Example |
| :--- | :--- | :--- | :--- |
| **T0** | `T0_linguistic` | Surface syntax, typos, formatting | Misspelled keywords, missing punctuation |
| **T1** | `T1_behavioral` | Agent cognition, goal framing | Semantic ambiguity, misleading persona cues |
| **T2** | `T2_structural` | Schemas, contracts, tool definitions | Altered JSON schemas, unexpected parameter types |
| **T3** | `T3_workflow` | State transitions, concurrency | Replayed steps, race conditions, skipped prerequisites |
| **T4** | `T4_security` | Security barriers, authorization | Prompt injections, token forgery, unauthorized access |
| **T5** | `T5_enterprise` | Complex systemic failures | Cascade service drops, tenant bleeding, cross-agent deadlocks |

---

## 2. 🧩 Core Contracts & Data Structures

The 3D Mutation Engine is built on immutable, type-safe contracts defined in `agentv_runtime.contracts`:

### `MutationCoordinate`
```python
from dataclasses import dataclass
from agentv_runtime.contracts import MutationTier


@dataclass(frozen=True)
class MutationCoordinate:
    vector: str
    operation: str
    tier: str = MutationTier.T1_BEHAVIORAL

    def to_dict(self) -> dict[str, str]:
        return {"vector": self.vector, "operation": self.operation, "tier": self.tier}
```

### `MutationContext`
Provides evaluation runtime state, deterministic random number generation, and event inspection to mutators during execution:

```python
@dataclass
class MutationContext:
    scenario: dict[str, Any]
    seed: int | None = None
    rng: random.Random = field(default_factory=random.Random)
    step_index: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    active_node: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### `MutationHandle` & `MutationRecord`
- `MutationHandle`: Returned by `ScenarioMutator.apply()` indicating whether the perturbation took effect, target metadata, and an optional rollback callback `revert()`.
- `MutationRecord`: Immutable audit record serialized into the execution trace (`run.jsonl`) and cryptographic certificate, ensuring tamper-evident provenance.

---

## 3. ⚡ Composable Algebraic Combinators

Mutators are first-class mathematical entities. They support algebraic composition via operator overloading (`+`) and higher-order combinator factories:

```python
from eval_runner.mutator import (
    after_event,
    between_steps,
    concurrent,
    probability,
    repeat,
    sequence,
)
```

### 1. Sequence Combinator (`+` or `sequence`)
Executes child mutators sequentially, chaining mutations across the context:
```python
# Operator overloading:
pipeline = mutator_a + mutator_b + mutator_c

# Explicit factory:
pipeline = sequence(mutator_a, mutator_b, mutator_c)
```

### 2. Repetition Combinator (`repeat`)
Applies a child mutator $N$ times:
```python
flaky_pipeline = repeat(noise_mutator, count=3)
```

### 3. Probability Combinator (`probability`)
Applies a child mutator with a calibrated Bernoulli probability $p \in [0.0, 1.0]$, driven by the seeded `MutationContext.rng`:
```python
jitter_pipeline = probability(delay_mutator, p=0.25)
```

### 4. Event & Lifecycle Combinators
Controls perturbation timing based on real-time execution events emitted on the event bus:
```python
# Apply mutation strictly after the agent attempts an authentication event:
auth_trap = after_event(token_expiry_mutator, "auth_attempt")

# Intercept environment updates immediately prior to state commit:
conflict_trap = before_commit(state_drift_mutator)

# Restrict mutation window to specific turns:
transient_glitch = between_steps(noise_mutator, min_step=3, max_step=6)
```

### 5. Concurrency & Race Combinator (`concurrent`)
Applies multiple conflicting operations simultaneously to simulate multi-threaded race conditions:
```python
race_condition = concurrent(tool_delay_mutator, state_drop_mutator)
```

---

## 4. 🛠️ Implementing a Custom Mutator

Custom mutators inherit from `ScenarioMutator` and declare their authoritative `MutationCoordinate`:

```python
import random
import uuid
from agentv_runtime.contracts import (
    MutationContext,
    MutationCoordinate,
    MutationHandle,
    MutationOperation,
    MutationTier,
    MutationVector,
)
from eval_runner.mutator import ScenarioMutator


class StaleTokenMutator(ScenarioMutator):
    name = "stale_token_injection"
    coordinate = MutationCoordinate(
        vector=MutationVector.AUTHORIZATION,
        operation=MutationOperation.EXPIRE,
        tier=MutationTier.T4_SECURITY,
    )

    def apply(self, context: MutationContext, rng: random.Random | None = None) -> MutationHandle:
        active_rng = rng or context.rng

        # Inspect current node headers or parameters
        if not context.active_node:
            return MutationHandle(
                mutation_id=f"stale_{uuid.uuid4().hex[:8]}",
                name=self.name,
                applied=False,
                coordinate=self.coordinate,
            )

        # Invalidate authorization token
        headers = context.active_node.setdefault("headers", {})
        headers["Authorization"] = "Bearer expired_test_token_v1"

        return MutationHandle(
            mutation_id=f"stale_{uuid.uuid4().hex[:8]}",
            name=self.name,
            applied=True,
            coordinate=self.coordinate,
            target="headers.Authorization",
            details={"original_token_replaced": True},
        )
```

---

## 5. 🔒 Deterministic Execution & Seed Chaining

To guarantee reproducible forensic audits:
1. Every evaluation run accepts a master `--seed <int>`.
2. The `MutationService` derives isolated sub-seeds for every pipeline stage:
   $$\text{sub\_seed} = \text{hash}(\text{master\_seed} \parallel \text{scenario\_id} \parallel \text{step\_index}) \pmod{2^{31}-1}$$
3. All random branching, character jitter, and combinatorial probabilities execute against `MutationContext.rng`, eliminating stochastic evaluation non-determinism.
4. Every applied mutation writes an immutable `MutationRecord` to `runs/<run_id>/run.jsonl`, binding directly into the trace's SHA3-256 seal and Verification Certificate.
