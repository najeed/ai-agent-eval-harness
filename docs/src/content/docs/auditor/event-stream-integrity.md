---
title: "Event Stream Forensic Integrity & Monotonic Boundaries"
description: "Auditor guide to trace ordering, monotonic terminal boundaries, finalization records, and tamper detection in run.jsonl."
---

# Event Stream Forensic Integrity & Monotonic Boundaries

In the AgentV Forensic Trust Protocol, an evaluation trace (`run.jsonl`) serves as the foundational evidentiary artifact. Auditors must verify not only the correctness of individual events, but also the mathematical integrity, ordering monotonicity, and immutability of the entire event sequence.

---

## 1. Trace Emission Lifecycle (Auditor View)

The execution engine streams events sequentially to `run.jsonl`:

```
┌────────────────────────────────────────────────────────┐
│ Phase 1: Session Initiation (run_start)                │
│ - Declared execution_mode (live, hybrid, simulated)    │
│ - Reproducibility contract & seed fingerprint          │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 2: Tactical & Adversarial Execution              │
│ - DAG Node Scheduling (execution_graph_node: running)  │
│ - Multi-turn Interactions (turn_start / turn_end)      │
│ - Tool Executions (tool_call / tool_result)            │
│ - HITL Policy Gating (hitl_pause / hitl_resume)        │
│ - State Parity & Hygiene Evidence                      │
│ - Graph Edge Transitions (execution_graph_edge)        │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 3: Mission Conclusion (strategy_end)             │
│ - Pass@K and attempt statistics aggregated             │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 4: Monotonic Terminal Boundary (run_end)         │
│ - Atomically embeds EvaluatorFinalizationRecord        │
│ - Strict EOF marker: NO events permitted after         │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 5: Transactional Sealing (agentv certify)        │
│ - SHA3-256 Digest over raw run.jsonl                   │
│ - Ed25519 Cryptographic Signature                     │
│ - Production of run_manifest.json, VC, and .sealed     │
└────────────────────────────────────────────────────────┘
```

---

## 2. Critical Security & Audit Invariants

### Invariant 1: Monotonic Terminal Boundary (Defect T4 Guard)
- **The Rule**: `run_end` MUST be the final event written to `run.jsonl`.
- **The Rationale**: Strategy conclusion (`strategy_end`) and all phase telemetry must complete *prior* to finalization. When `run_end` is emitted, it encapsulates the complete state of the run inside its `finalization` block.
- **Enforcement**: If any event appears in the stream after `finalization` is parsed, the `CertificationService` flags a fatal `Monotonic terminal boundary violation`, rejects certification, and fails closed with:
  ```
  [Certification] FAIL CLOSED: Inconclusive outcome for <run_id>: missing or conflicting terminal
  ```

### Invariant 2: The `EvaluatorFinalizationRecord`
The terminal `run_end` payload strictly requires a `finalization` block containing:
- **`scenario_hash`**: FIPS 202 SHA3-256 digest of the canonicalized scenario JSON (`sha3_256:...`). Guarantees the agent was tested against an untampered specification.
- **`execution_manifest_hash`**: Digest of the execution parameters (run ID, scenario ID, declared execution mode).
- **`evidence_root_hash`**: Merkle root of all recorded assertion outcomes and node verdicts.
- **`finalization_hash`**: Authoritative hash computed over all fields of the finalization record itself.

If the claimed `finalization_hash` does not match the recomputed digest, the trace is rejected as tampered.

### Invariant 3: Execution Truth & Anti-Masquerade (Defect T1 Guard)
- The harness requires an explicit `execution_mode` (`live`, `hybrid`, `record_replay`).
- If an operator fails to declare `execution_mode`, the engine defaults to `simulated` and marks `provisional: true`.
- **Audit Policy**: Provisional certificates can NEVER be cited for industrial safety compliance, financial audit defense, or security validation.

---

## 3. Auditing a Run via CLI

To verify a trace independently:

```bash
# 1. Cryptographic integrity check (recalculates SHA3-256 over run.jsonl and checks .sealed)
python -m eval_runner.cli verify --run-id <run_id>

# 2. Release Gate check (verifies signature, VC schema, and ledger commitments)
python -m eval_runner.cli gate --run-id <run_id> --verify-ledger

# 3. Inspect raw terminal finalization record
jq '.finalization' runs/<run_id>/run_manifest.json
```

If any bit of `run.jsonl` was modified post-execution, `agentv verify` and `agentv gate` will reject the vault immediately with a non-zero exit code.
