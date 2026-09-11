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
| `OBJECTIVE` | `objective` | Goal definitions, proxy rewards, constraint trade-offs, and metric gamification. |
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

---

## 6. 🏗️ Modular Vector Sub-Engines

The mutation engine is organized into 9 domain-focused vector sub-engines inherited by `CoreMutator`:

1. **`InputMutators`**: Prompt injections, delimiter hijacking, prompt truncation, semantic paraphrasing, and encoding corruption.
2. **`ContextMutators`**: Context window overflowing, history pruning, persona subversion, and out-of-order turn insertion.
3. **`MemoryMutators`**: Memory key deletion, stale memory overwrite, cross-session leakage, and memory poisoning.
4. **`RetrievalMutators`**: RAG chunk corruption, document omission, semantic rank inversion, retrieval chunk splitting, and retrieval source swapping.
5. **`ToolMutators`**: Parameter type swapping, required parameter dropping, malformed payloads, schema hallucination, latency boundary injection, and tool contract violations.
6. **`StateMutators`**: VFS file deletion, permission tampering, transaction rollback failures, partial commits, stale commits, duplicate commits, and commit after cancellation.
7. **`AuthorizationMutators`**: Scope stripping, token expiration, privilege escalation, stale approval reuse, approval payload mismatch, approval revocation, and approval race conditions.
8. **`TemporalMutators`**: Clock skew, timeout boundaries, delay injection, cancel race conditions, and lease expiration.
9. **`ObjectiveMutators`**: Metric gaming (exploiting proxy metrics), proxy goal substitution, constraint trade-offs, subgoal cannibalization, and reward hacking.

All sub-engines export their primitives directly, while `CoreMutator` provides backwards-compatible unified dispatch across all mutation coordinates.

---

## 7. 🏛️ Southbound Fault Interception Architecture

### Why Scenarios Must Remain Declarative
A common architectural inquiry is: *Why can't we instantiate custom `BaseEvalPlugin` classes and inject them directly into scenario steps for workflow and state mutations?*

The evaluation harness strictly enforces an **architectural separation of concerns** between scenario declarations and runtime fault execution:

```
┌────────────────────────────────────────────────────────┐
│               Scenario Definition (AES)                │
│    - Declarative JSON/YAML Schema                      │
│    - RFC 8785 Canonical JSON Deterministic Hash        │
│    - Portable, version-controlled, zero code execution │
└──────────────────────────┬─────────────────────────────┘
                           │ step.mutations (declarative)
                           ▼
┌────────────────────────────────────────────────────────┐
│          Session & Southbound Runtime Engine           │
│    - SessionOrchestrator._execute_node()               │
│    - RuntimeMutationPlugin (BaseEvalPlugin)            │
│         ├─ on_step_start(step_id, mutations)          │
│         ├─ on_tool_request(tool_name, payload)         │
│         ├─ on_before_commit(tx_id, state_diff)         │
│         ├─ on_rollback(tx_id, reason)                  │
│         └─ on_approval_request(action, payload)        │
└────────────────────────────────────────────────────────┘
```

1. **Portability & Deterministic Hashing (RFC 8785)**: Scenarios must serialize canonically to enable cryptographic signing, SHA-256 certificate generation, and cross-language benchmarking. Embedding executable Python objects breaks serialization and prevents verification.
2. **Security & Untrusted Scenarios**: Scenarios frequently originate from external benchmark datasets, third-party audits, or untrusted repositories. Permitting executable plugins directly within scenario step schemas creates an arbitrary Remote Code Execution (RCE) vulnerability.
3. **Southbound Interception vs. Northbound Specification**:
   - The **Scenario (Northbound)** declares *what* perturbations should occur:
     ```json
     {
       "id": "step-3",
       "mutations": [
         {"type": "partial_commit", "parameters": {"fail_step": 1}},
         {"type": "approval_race", "parameters": {"window_ms": 50}}
       ]
     }
     ```
   - The **Runtime Interceptor (`RuntimeMutationPlugin`, Southbound)** listens to lifecycle events (`on_step_start`, `on_tool_request`, `on_before_commit`, `on_approval_request`) and injects real faults into tool execution, database transactions, and human-in-the-loop approvals.

---

## 8. ⚙️ Engine Mechanics & Memory Model

A critical architectural question is how mutations interact with scenario files and runtime memory:

### 1. In-Place File Safety (Immutability Guarantee)
The mutation engine **never** modifies the original scenario JSON/YAML file on disk:
- Every invocation of `MutationService.mutate_scenario(scenario_data, ...)` immediately performs `safe_scenario = copy.deepcopy(scenario_data)`.
- The source document remains pristine and unpolluted by synthetic perturbations.

### 2. In-Memory Execution vs. Disk Materialization
The engine supports two operational paths depending on whether evaluation is running dynamically or generating offline variants:

| Path | Disk Mutation | In-Memory Mutation | Artifact Produced |
| :--- | :---: | :---: | :--- |
| **In-Run Evaluation** (`agentv eval`) | ❌ None | ✅ Active | Executed 100% in RAM via `copy.deepcopy()` and passed directly to `SessionOrchestrator`. No temporary scenario files are created. |
| **CLI Scenario Mutation** (`agentv mutate`) | ❌ No source edits | ✅ Active | Writes the mutated scenario variant to a new file specified by `--output <path>`. |
| **Synthetic Scenario Generation** (`SyntheticService.generate_variants`) | ❌ No source edits | ✅ Active | Materializes $N$ distinct mutated scenario JSON files to `scenarios/synthetic/{parent_id}_{strategy}_{idx}.json`. |

---

## 9. 🔀 Combinator Execution Semantics

Mutator combinators compose mathematically to form complex stress pipelines:

### 1. Sequential Chaining (`SequenceMutator` or `m1 + m2`)
- **Execution**: Evaluated strictly in-memory in left-to-right order:
  $$\text{Scenario}_{n} = m_n(\dots(m_2(m_1(\text{Scenario}_0))))$$
- Each child mutator receives the deep-copied output of its predecessor.
- If any mutator fails, a mandatory mutator raises a fail-closed `RuntimeError`, while optional mutators log a warning and pass intermediate state downstream.

### 2. Iterative Repetition (`RepeatMutator` or `repeat(m, count)`)
- Sequentially reapplies the target mutator $N$ times against the active context.
- Used to compound character noise, cascade API latency, or prune multiple memory keys.

### 3. Calibrated Probability (`ProbabilityMutator` or `probability(m, p)`)
- Drives a Bernoulli trial $X \sim \text{Bernoulli}(p)$ using the deterministic `MutationContext.rng`.
- If $X = 1$, the mutator applies; if $X = 0$, it returns a non-applied `MutationHandle(applied=False)` and preserves the scenario unchanged.

### 4. Event & Temporal Predicates (`ConditionalMutator`)
- Triggers mutations only when runtime execution context satisfies dynamic predicates:
  - `after_event("auth_attempt")`: fires once the event appears in `MutationContext.history`.
  - `before_commit()`: intercepts execution prior to state transition persistence.
  - `between_steps(min, max)`: constrains the perturbation window to specific turn boundaries.

### 5. Simulated Concurrency & Races (`ConcurrentMutator` or `concurrent(m1, m2)`)
- Simulates race conditions by cloning context, applying conflicting mutations concurrently, and merging state changes with `simulated_race: True` markers.
- Exercises an agent's ability to handle split-brain state, non-idempotent updates, and time-of-check to time-of-use (TOCTOU) anomalies.

---

## 10. 🧬 4-Layer Lineage & Provenance Tracking

To ensure regulatory audit defensibility, every evaluation run is bound to its exact mutated scenario version through **four cryptographic and metadata lineage layers**:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 1: Authoritative RFC 8785 Canonical Scenario Hash                │
│   scenario_hash = sha3_256(JCS(clean_scenario_data))                   │
│   - Embedded in RUN_START event                                        │
│   - Verified by TraceVerifier against package manifest                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ Layer 2: Parent-Child Scenario Lineage Metadata                        │
│   - metadata.parent_scenario_id: root unmutated scenario ID            │
│   - metadata.mutation_strategy: applied perturbation type              │
│   - metadata.synthetic: true flag identifying synthetic variant        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ Layer 3: Deterministic Seed Chaining & Reproducibility Contract        │
│   sub_seed = hash(master_seed || scenario_id || step_index)            │
│   reproducibility_fingerprint embedded in evaluation contract          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ Layer 4: In-Trace Mutation Audit Records                               │
│   MutationRecord(id, vector, operation, tier, target, step, timestamp) │
│   - Emitted directly to runs/<run_id>/run.jsonl                        │
│   - Sequentially bound into trace seal and Ed25519 signature envelope   │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. Canonical Scenario Hash (`scenario_hash`) via RFC 8785 JCS
- Computed via `agentv_runtime.manifest.compute_scenario_hash()` using RFC 8785 JSON Canonicalization Scheme (JCS).
- When a run initiates, `eval_runner/runner.py` emits the `RUN_START` event embedding the full scenario and its canonical `scenario_hash`.
- `TraceVerifier` and `CertificationService` recompute the hash from the executed scenario data and require exact match:
  ```python
  if computed_scen_hash != pkg.scenario_hash:
      raise ValueError(
          f"ScenarioHashMismatch: package={pkg.scenario_hash} computed={computed_scen_hash}"
      )
  ```
  Any tampering with mutated prompts, tools, or step directives causes immediate fail-closed certification rejection.

### 2. Parent-Child Lineage Metadata
- When synthetic mutant scenarios are generated via `SyntheticService.generate_variants()`:
  - `scenario["id"]` becomes `{parent_id}_{strategy}_{idx}`.
  - `scenario["metadata"]["parent_scenario_id"]` records the unmutated ancestor.
  - `scenario["metadata"]["mutation_strategy"]` records the strategy (e.g. `context_bleed`, `partial_commit`).
  - `scenario["metadata"]["synthetic"] = True` marks the file as synthetic.

### 3. Deterministic Seed Derivation & Reproducibility Fingerprint
- Evaluation runs accept a master `--seed <int>`.
- The engine derives isolated sub-seeds:
  $$\text{sub\_seed} = \text{hash}(\text{master\_seed} \parallel \text{scenario\_id} \parallel \text{step\_index}) \pmod{2^{31}-1}$$
- The seed and configuration state are hashed into a `reproducibility_fingerprint` attached to the run manifest, ensuring any auditor can re-execute the exact same stochastic perturbations.

### 4. In-Trace Cryptographic Mutation Records (`MutationRecord`)
- During execution, every applied perturbation generates an authoritative `MutationRecord`:
  ```python
  @dataclass(frozen=True)
  class MutationRecord:
      mutation_id: str
      name: str
      vector: str
      operation: str
      tier: str
      target: str
      applied_at_step: int
      timestamp: str
      details: dict[str, Any]
  ```
- This record is written directly into `runs/<run_id>/run.jsonl`.
- The `FlightRecorderPlugin` incorporates the event into the tamper-evident hash chain and detached Ed25519 trace seal (`.trace_seal`), proving unequivocally which run executed which specific mutations.


