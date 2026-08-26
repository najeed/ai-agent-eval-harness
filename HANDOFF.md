# HANDOFF — Development State & Continuation Guide

**Date:** 2026-08-26  
**Branch:** `dev`  
**Pinned commit:** `eb36702b4` (HEAD has moved past it; use `git log --oneline -1` to verify)  
**Auxiliary doc:** `scratch/audit-remediation-eb36702b4.md` (untracked, local-only — contains the full checklist)

---

## What's Done

### Phase 1 — Release Blockers (all 10 items)

| Item | Defect | Verification |
|---|---|---|
| P1.1 | V01 — compensation counter dead code | `test_dropped_compensation_prevents_workflow_completion` (mutation-verified) |
| P1.2 | V07 — strategy_end truncates SSE stream | `test_contract_strategy_end_does_not_truncate_multi_stage_runs` (mutation-verified) |
| P1.3 | V08 — LiveDebugger array-order state | `_seq`-normalized event stream in `buildTraceGraph` |
| P1.4 | V08 — false-complete graph | `instanceOwner` map + `droppedEdgeCount` chip |
| P1.5 | V09 — false-positive reachability | `'configured'` status tier; `AgentTargetSelector.tsx` |
| P1.6 | V05 — Docker/CI UI build gate | multi-stage Dockerfile, CI gate, `ui/visual-debugger` deleted |
| P1.7 | V06 — publisher_failed unreachable | `App.tsx` catch routes `kind:'publisher'` |
| P1.8 | V04 — credentialed CORS any origin | `AGENTV_ALLOWED_ORIGINS` config; same-origin default |
| P1.9 | V03 — ephemeral JWT silent fallback | RuntimeError in prod; logger.warning otherwise |
| P1.10 | V10 — oracle INVALID outcomes | sentinel `__unobserved_source__` + typed evidence rows |

### Phase 2 — Kernel Hardening (ALL 10 items complete)

| Item | Status | Notes |
|---|---|---|
| P2.1 / P2.2 | DONE | Per-execution-instance context: `ExecutionInstanceContext` with branch-isolated sandboxes (`sandbox.fork()`), isolated conversation ledgers, and instance-scoped turn execution. |
| P2.3 | DONE | Ambiguous successor sets rejected at compile time (rejects multiple sequential edges, mixed sequential/parallel, mixed condition/parallel). |
| P2.4 | DONE | Join epochs: `ExecutionToken.epoch` + `ReadyItem.epoch`; structural/repair edge split; epoch invalidation |
| P2.5 | DONE | Over-cap evidence: `batch_cap`, `join_token_cap`, `join_satisfied_cap` phases; `dropped_after_cap_node_ids` outcome field |
| P2.6 | DONE | Authoritative evaluation plan (`CompiledEvaluationPlan`, `CompiledOracle`) with typed oracle requiredness checks (`PASS`, `FAIL`, `INVALID`, `NOT_APPLICABLE`). |
| P2.7 | DONE | Deterministic final-verdict function: explicit `NodeVerdict` integration across verification, policy, parity, and overall outcomes. |
| P2.8 | DONE | Interceptor chain: mandatory vs optional classification (fail-closed on critical integrity verifiers). |
| P2.9 | DONE | `SessionManager.fork()` removed from capability surface (was fake — ignored both arguments); tests updated to assert absence |
| P2.10 | DONE | Verdict host separation: synthetic fallback and global-evaluation row excluded from task aggregation; `_is_task_row()` filter in reporter; `global_evaluation_status` renamed; all_task_results appends verdict host once |

### Phase 3 — Product Spine & UX (Key items complete)

| Item | Status | Notes |
|---|---|---|
| P3.3 | DONE | `ENABLE_DEMO` defaults strictly to `false` in production. |
| P3.4 | DONE | Visual console claims qualified; demo mode banner and warning indicators clearly demarcated. |
| P3.7 / P3.8 | DONE | Plugin route error diagnostics and certificate verification indicators surfaced. |

### Supply-Chain Hygiene (Dependabot)

30 alerts across `docs/`, `vscode-extension/`, `ui/visual-console/` all resolved via lockfile regeneration + overrides. See `scratch/audit-remediation-eb36702b4.md` §6 for details.

---

## What's Pending

All Phase 1 and Phase 2 items from the audit feedback have been resolved and verified with tests. Future iterations can focus on additional modular decomposition of `session.py` and optional extended mock simulator extensions.

### Open Decisions (2 remaining)

- **Extension iframe isolation** (Reviewer A vs B/C): decide whether to iframe-isolate extensions
- **Evaluation rebuild scope** (five-contract rebuild vs surgical fixes): agreed direction — incremental on top of `NodeVerdict`

---

## Key Architecture Changes

### Epoch-scoped join tokens (`eval_runner/workflow_interpreter.py`)

- `ExecutionToken.match_key` → `self.epoch` (was `(lineage, iteration)`)
- `_STRUCTURAL_EDGE_TYPES` / `_REPAIR_EDGE_TYPES` split: retry/compensation/error/timeout edges BYPASS join math
- `_try_join` repair bypass: activates target directly, preserving arriving token's epoch
- `_try_join` structural: groups strictly by epoch; firing invalidates all unused same-epoch tokens
- `ReadyItem.epoch` propagated; minted at multi-edge fan-outs (`len(edges)>1`) and true merges (`len(consumed)>1`)
- `_new_epoch()` counter: `ep1`, `ep2`, ...

### Verdict host separation (`eval_runner/session.py`, `eval_runner/reporter.py`)

- **session.py**: `verdict_target` is always a dedicated synthetic host dict; never bolted onto a real task result. Global branch: `global_results["global_evaluation_status"]` (not `"status"`). Fallback branch: `"synthetic": True`, no `"status"` key. All partitions converge to a single unconditional `all_task_results.append(verdict_target)`.
- **reporter.py**: `_is_task_row(tr)` — filters out dicts containing `"workflow_verdict"` or `"synthetic": True`. Applied at both HTML report `all_tasks` build and console summary iteration.

### fork() removal

- `SessionManager.fork()` removed (was ignoring both arguments per code comment). Production code never called it. Three test files updated: `test_core_session.py`, `test_session_advanced.py`, `test_security_audit.py`.
- Why was this removed? The code comment indicated that it was there for researchers to experiment. Assess if this is useful functionality that we are losing.

---

## CI Infrastructure Changes

| Change | File | Reason |
|---|---|---|
| `ui-build` stage `FROM node:22-alpine` | `Dockerfile` | Vite 8 / Astro 7 require Node ≥22 |
| `setup-node` version `'22'` | `.github/workflows/ci.yml` | Same |
| `ui-test` job builds bundle + hard-fails if `dist/index.html` missing | `.github/workflows/ci.yml` | P1.6 gate |
| `ui/visual-console/src/lib/aesDocument.ts` tracked | `.gitignore` negation added | `lib/` was silently excluding it |
| `.dockerignore` added | root | Keeps build context lean |

---

## Repo-Level Patterns

### Test conventions for interpreter tests (`tests/unit/core/test_workflow_interpreter.py`)
- `_plan(scenario)` — compiles via `compile_workflow` + injects trivial success_criteria into nodes lacking oracles
- `_run(plan, executor)` — creates `WorkflowInterpreter` with identity + ctx_provider, runs `interp.run(executor)`
- `executor` signature: `async def executor(node_ir, exec_id, parent) -> dict`
- Epoch contracts: `test_join_rejects_cross_iteration_tokens`, `test_join_all_never_pairs_tokens_across_loop_waves`, `test_join_all_converges_same_wave_despite_producer_iteration_skew`, `test_join_n_of_m_leftovers_do_not_inflate_later_waves`

### Supply-chain overrides active
- `ui/visual-console`: `{"dompurify": "^3.4.14"}`
- `docs`: `{"nanoid": "^6.0.1"}`
- `vscode-extension`: `{"js-yaml": "^4.3.1", "brace-expansion": "^2.1.3"}`

---

## Quick Start for Next Session

```bash
# 1. Fast check: what changed since last session
git log --oneline -3

# 2. Run the interpreter kernel tests (fastest feedback loop)
python -m pytest tests/unit/core/test_workflow_interpreter.py -q

# 3. Run the full kernel suite (1244 tests, ~2 min with xdist)
python -m pytest tests/unit/core -q -n auto

# 4. Run the console suite (469 tests)
python -m pytest tests/unit/console -q -n auto

# 5. Start with P2.3 (compiler ambiguous successor sets) — the smallest
# remaining Phase 2 item and closest to the kernel work already done.
```

---

## Known Gotchas

- `npm audit` is broken behind the SafetyCLI registry mirror (`https://pkgs.safetycli.com/`) — "Invalid request payload JSON format". Verify dependency versions via direct lockfile inspection instead.
- Dependabot auto-PRs are **paused** — loud booting. Manual fix push closes alerts; to resume auto-PRs, merge one Dependabot PR or re-enable in Settings → Code security.
- `ui/visual-debugger/` was deleted (8 CDN-loaded files). Git-recoverable via `git checkout HEAD~1 -- ui/visual-debugger/` if needed.
- `@types/dagre` is `^0.7.54` matching dagre `^0.8.5` — the dagre 2.0 phantom version was reverted.
- The `test_security_audit.py::test_fork_bomb_depth` test now asserts `not hasattr(session, "fork")` — fork removal was intentional.
- `scratch/audit-remediation-eb36702b4.md` is gitignored; copy it to a tracked location if you want it preserved across branch switches.