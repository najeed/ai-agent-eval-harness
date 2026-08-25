# HANDOFF — Verification-Kernel Hardening Session (continuation)

Read this first in a new session. Authoritative resume point. Update it as
items land; delete once the remaining-work section is empty (user's ritual).

---

## 0. Doctrine additions from this session (BINDING)

1. **Ask before forks.** When a review/remediation says "X **or** Y", that is
   the user's decision, not ours. This session logged four violations
   (analyzer gate, catalog gate, VC required-vs-additive, silent UI
   deferrals) — three were corrected only after user pushback.
2. **Never append revision sections to exhaustive guides.** Integrate into
   the existing sections in place; guides are single-source-of-truth.
3. Foreground single pytest invocation only (`-n auto`); no Start-Process.
4. No VC version bumps without explicit approval (the 3.0.0
   `execution_mode`-required change rode an explicit 2026-08 waiver).
5. All work stays UNCOMMITTED; user commits explicitly.
6. Verifier truth-level matching is EXACT (no case/space normalization) —
   mirrors SessionManager's fail-closed parsing.

## 1. ⚠ IMMEDIATE LOOSE END (fix before anything else)

**RESOLVED — verified this session.** `eval_runner/runner.py` call site uses
`new_run_id(scenario["id"])` (line ~150); helper at lines 33–42;
`tests/unit/core/test_run_identity.py` exists and passes.

## 2. Landed this session (all verified green individually)

Full last sweep (user-run): **2988 passed / 4 failed → all 4 fixed &
verified locally since** (analyze-acquire assertion, spec-test path anchor,
HITL CI contract test, compliance fail-closed tests). Re-run full `-n auto`
before any commit.

### 2.a Verified ALREADY-IMPLEMENTED (audit this session — do not redo)

- **§1 loose end**: `new_run_id` extraction complete (see above).
- **3.1 Edge Inspector**: `aesDocument.ts` carries `edge_type`/`priority` on
  `UiEditPatch.edges[]` (+ `EDGE_TYPES` literal guard); ScenarioComposer has
  `selectedEdgeId` state, `onEdgeClick`, Edge Inspector panel; round-trip
  docmodel cases present ("survive project→patch unchanged", "absent stay
  absent").
- **3.2 Import-review modal**: `pendingImport` state + `commitPendingImport`
  / `discardPendingImport`; import never mutates state without Apply.
- **3.3 Extensions panel + contracts**: Settings.tsx read-only "Extension
  Host" inventory (`/api/nav`, `EXTENSION_CONTRACT_VERSION` badge);
  `tests/unit/console/test_extension_host_contracts.py` present.

### 2.b Implemented THIS session

- **3.4 Endpoint-schema suite**: NEW `spec/console-api/` — 9 locked GET
  contracts (`runs`, `scenarios`, `nav`, `system-status` (= `/api/status`),
  `doctor` (`/v1/doctor`), `metrics`, `agent-targets`,
  `evidence-packages`, `certificate`). NEW
  `tests/unit/console/test_gui_endpoint_schemas.py`: bare Flask app +
  production-parity blueprint registration (incl. core_bp /v1 shims),
  config jail monkeypatches, jsonschema Draft7 validation, failures print
  field-level diffs. All 9 green.
- **3.5 Quick-win tests**:
  - a) `test_join_rejects_cross_iteration_tokens` (appended to
    `test_workflow_interpreter.py`): direct `_try_join` probe; iter-9 token
    cannot complete iter-1's AND-join; same-key sibling activates + consumes.
  - b) `test_interpreter_owned_deadline_routes_timeout`: node `timeout: 0.05`
    vs executor sleep 0.3 → triage TIMEOUT, `record.timed_out True`,
    `transitions[0].reason == 'timeout_route'`, workflow still succeeds.
  - c) `test_parallel_wave_runs_concurrently_wall_clock`: two 0.25s branches
    in one wave < 0.45s wall (NOTE: root must not sleep — wave time is
    measured after root completes).
  - d) NEW `tests/unit/core/test_consensus_semantics.py` (10 async tests):
    Majority_Vote pass/fail tallies, quorum-fail ⇒ loud evaluated=false,
    unknown-strategy ⇒ evaluated=false, ija INCONCLUSIVE overrides PASS,
    Absolute_Unanimity buckets, Weighted_Average mean threshold,
    Luna-1→config.JUDGE_PROVIDER provisioning alias, no-expected-message
    never judges. Patches `LLMProviderFactory` + `MetricRegistry.get`.
- **CI fix (`test_hitl_pause_resume`)**: the test was ambient-env dependent —
  GitHub Actions sets `CI=true`, which routes `_handle_hitl` into the
  intentional fail-closed HITL_UNRESOLVED branch (no HITL_RESUME event,
  single agent call) ⇒ assertion failed only on CI. Fixed by pinning
  `monkeypatch.delenv("CI")` for the handshake test, plus NEW
  `test_hitl_ci_mode_fail_closed` locking the CI contract (PAUSE emitted,
  RESUME never, triage_tag=HITL_UNRESOLVED). Verified under both envs.

- **Kernel P0 1–12 + E**: `NodeVerdict` (execution/verification/policy/
  parity/overall) authoritative routing; typed oracle outcomes
  PASS/FAIL/INVALID/NOT_APPLICABLE; VERIFICATION_FAILED/POLICY_DENIED/TIMEOUT/
  HITL_UNRESOLVED triage literals; token-based interpreter with generation-
  scoped joins (`match_key=(lineage, iteration)`), join modes all/any/n_of_m,
  true parallel waves (asyncio.gather), interpreter-owned per-node deadlines,
  explicit entry declaration (comp/self edges never root), UUIDv7 run IDs
  (`runner.new_run_id` — see §1), instance-keyed evidence +
  hashed transition rows, execution_mode↔adapter consistency guard,
  HITL CI auto-approval REMOVED, multi-tool concurrency w/ depends_on,
  reproducibility contract v1.1.0 (+ evaluator fingerprint & provenance).
- **Fabricated trio**: analyzer = REAL repo scan (tree-stream default,
  tarball fallback, SSRF guard, tokens via env/--token-file, latency knobs);
  catalog install = REAL path-based pack installer (+ committed sample at
  `samples/packs/sample-pack/`); compliance fail-closed
  (`behavioral_metrics: not_evaluated_in_oss`).
- **Consensus IMPLEMENTED**: `Session._evaluate_consensus` (Majority_Vote /
  Absolute_Unanimity / Weighted_Average; ija_threshold ⇒ INCONCLUSIVE;
  quorum via real provider creation; unprovisionable ⇒ loud evaluated=false).
- **VC Trust B**: `execution_mode` REQUIRED in vc.schema.json (waiver, no
  bump) incl `"unknown"` enum; verifier stamps unconditionally + whitelist
  (junk ⇒ unknown+provisional); certify reads run vault truth level;
  provisional WARN; session loud-default banner + declared flag on run_start.
- **GUI truth batch**: debugger single-controller SSE (dedupe/gap/REPLAYING/
  FINISHED), unified integrity verdict consuming live gaps, planned/executed/
  divergence layers, waterfall w/ tool/assertion markers, fit-once+Fit,
  Focus-node, RCA de-AI'd + NO_ANALYSIS_AVAILABLE + SUSPECTED drawer,
  nodesConnectable=false + hideAttribution; composer canonical-doc model
  (`src/lib/aesDocument.ts`, projection refusal, patch-not-rebuild),
  unified server validation both modes, Untitled Draft defaults,
  "Apply changes" label; Dashboard zero-state→spec-import CTA + integrity
  chips (Runs+Dashboard); runs verdict literals NOT_EXECUTED/ERROR;
  run_id link fixes; TrustCenter /api/v1 paths; scoped 401/403 toast;
  backend-authoritative tier BOTH ends; Workflow ?scenario_id preselect +
  bound-revision display; evaluate response carries scenario_hash;
  CSP/security headers (jsdelivr+blob allowlist).
- **Specs**: NEW dirs `spec/{agentv-package,scenario-pack,agent-targets,extensions}/`
  each schema+exhaustive guide+Reference Walkthrough; VC guide Lesson 4
  (in-place); RUNS guide Lessons 6–7 (in-place). Contract tests:
  `tests/unit/spec/test_spec_contracts.py` (6),
  `tests/unit/console/test_agentv_package_schema.py` (3),
  `tests/unit/core/test_vc_truth_level.py` (5).

## 3. REMAINING WORK (none — §3.1–3.5 all landed, see §2)

All four approved items plus the loose end are DONE. Per the ritual this
file can be deleted once the user confirms — nothing remains open:

### ✅ RESOLVED this session: UI status-path mismatch

`App.tsx:526` and `VerificationWorkflow.tsx:94` fetched `/api/system/status`
(a route that never existed server-side ⇒ both health gates were stuck in
error state). Fixed to fetch **`/api/status`** (the authoritative
`system.runtime_status` route; locked by `spec/console-api/system-status.schema.json`).
Verified on a LIVE werkzeug-served instance of production `create_app()`:
`GET /api/status → 200` (RuntimeHealth payload); `/api/system/status → 404`;
rebuilt bundle contains zero references to the dead path.


## 4. Ratification queue (implemented unilaterally — flag if wrong)
- Consensus sub-semantics: `Luna-1` aliases to config.JUDGE_PROVIDER default;
  INCONCLUSIVE overrides PASS only; strategies = Majority_Vote |
  Absolute_Unanimity | Weighted_Average.
- CSP allowlist: script-src `'self' https://cdn.jsdelivr.net blob:` (Monaco
  CDN + extension Blob-mount seam); worker-src blob:.
- `AGENTV_OFFICIAL_PUBLISHERS` env defines 'official' tier publishers.
- Entry-rule exemption: legacy edge-less chains keep declaration-order entry.
- Verifier mode rule now exact-match strict (aligned to session parser).

## 5. Gates (run ALL before reporting done)
```
python -m pytest --ignore=tests/functional/test_scenario_compliance.py -n auto -q
ruff check .
bandit -ll -r .   # scope to source dirs; full-repo scan crawls venv/dist
npm run build --prefix ui/visual-console
npm run test:docmodel --prefix ui/visual-console
```
**FULL SWEEP THIS SESSION (all five gates):**
- pytest `-n auto`: **3017 passed / 3 skipped / 0 failed**, 2 COLLECTION
  ERRORS that are pre-existing optional-dep gaps, NOT regressions:
  `tests/property/test_schema_property_based.py` (no `hypothesis` in venv),
  `tests/performance/test_interception_benchmarks.py` (no `pytest_benchmark`).
- ruff check . : All checks passed.
- bandit (-ll, scoped to eval_runner/agentv_runtime/dataproc_engine/tests/
  sample_agent/scripts/plugins): no MEDIUM+ findings; only `nosec`
  bookkeeping warnings.
- npm build: green (chunk-size warning only). docmodel: pass 17 / fail 0.
Coverage gate 90% (was 94.54%).

## 6. Verify quickly anytime
```
python -m pytest tests/unit/core/test_workflow_interpreter.py tests/unit/core/test_consensus_semantics.py tests/unit/core/test_run_identity.py tests/unit/core/test_vc_truth_level.py tests/unit/spec tests/unit/console/test_gui_endpoint_schemas.py -q
python -m pytest tests/unit/handlers/test_catalog.py tests/unit/core/test_analyzer.py -q
npm run build --prefix ui/visual-console
git status --short
```
npm run build --prefix ui/visual-console
git status --short
```

## 7. Dirty-file map (top level)
Kernel: runner/session/workflow_interpreter/execution_ir/reproducibility/
verifier/compliance/catalog/analyzer/cli/handlers/environment · console
routes: runs/scenarios/trust/evidence/agent_targets(new)/routes __init__ ·
agentv_runtime: versions/results/evidence_graph · spec: vc/runs edits + 4 new
dirs · samples/packs/sample-pack (new) · ui: App/Dashboard/RunsReports/
VerificationWorkflow/ScenarioComposer/LiveDebugger/TrustCenter/Settings?
(no)/AgentTargetSelector/CommandPalette/RunDetailView/lib+aesDocument(new)/
types/agent-target(new)/pages deletions(EvaluationRunner,TraceExplain) ·
tests: many modified + new files listed above · eval_runner/config.py
(AGENT_TARGETS_PATH), console/app.py (CSP+blueprint), auth n/a.
