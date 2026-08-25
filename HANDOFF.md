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

**`eval_runner/runner.py` — `new_run_id()` extraction is HALF-APPLIED.**

- Helper exists at lines ~33–42 (module level, imports fine).
- Call site (~line 154–155, inside `DefaultRunner.run`) still uses the OLD
  inline duplicate:
  ```python
  unique_suffix = _u7().hex if callable(_u7) else uuid.uuid4().hex
  effective_run_id = run_id or f"run-{scenario['id']}-{unique_suffix}"
  ```
- Fix: replace those two lines with
  ```python
  effective_run_id = run_id or new_run_id(scenario["id"])
  ```
- Then add `tests/unit/core/test_run_identity.py`:

```python
import re

from eval_runner.runner import new_run_id


def test_new_run_id_shape_and_uniqueness():
    ids = {new_run_id("loan_flow") for _ in range(1000)}
    assert len(ids) == 1000
    pattern = re.compile(r"^run-loan_flow-[0-9a-f]{32}$")
    assert all(pattern.match(i) for i in ids)
```

Run: `pytest tests/unit/core/test_run_identity.py -q` + ruff.

## 2. Landed this session (all verified green individually)

Full last sweep (user-run): **2988 passed / 4 failed → all 4 fixed &
verified locally since** (analyze-acquire assertion, spec-test path anchor,
HITL CI contract test, compliance fail-closed tests). Re-run full `-n auto`
before any commit.

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

## 3. REMAINING WORK (4 items, approved but not started)

### 3.1 Edge Inspector (composer)
Files: `ui/visual-console/src/lib/aesDocument.ts`,
`src/pages/ScenarioComposer.tsx`, `tests/document-model/aesDocument.test.ts`.
1. Extend `UiEditPatch.edges[]` entries: optional `edge_type?: string`
   (validate against `_EDGE_TYPE_ALIASES` keys exported from python? mirror
   list in TS: sequential/condition/default/error/timeout/retry/
   compensation/parallel/join), `priority?: number`.
2. `patchCanonicalDocument`: spread them onto existing edge objects exactly
   like `condition`; unknown fields still preserved.
3. Composer: add `selectedEdge` state; `onEdgeClick={(params)=>setSelectedEdge(params.edgeId)}`
   via `onEdgesChange` selection OR ReactFlow `onEdgeClick` prop. Panel
   (render when selectedEdge): type select (8 types), priority number,
   condition textarea (shown when type=condition), wired through
   `updateEdgeField(id, field, value)` which maps to `edges` state
   `data.{field}` so getAESJson picks it up.
4. Round-trip tests: edge_type/priority survive project→patch unchanged;
   condition preserved; unknown sibling fields intact.
Exit: docmodel suite green incl new cases; tsc build green.

### 3.2 Import-review modal (composer)
State: `pendingImport: {doc:any; preview:{nodes:number;edges:number}; ambiguities:string[]} | null`.
In `handleImportSpec`: on success DO NOT commit; compute
`projectToCanvas(parsed)` inside try (refusal path already handled), build
ambiguities = nodes missing `task_description`, edges lacking `condition`
when >1 outgoing from same source, absent `evaluation` block; stash
pendingImport; render modal listing counts + ambiguity bullets +
[Review in canvas] (commit existing flow) / [Discard].
Exit: import never mutates state without explicit Apply.

### 3.3 Extensions panel + 4 contract tests
Panel: `src/pages/Settings.tsx` new section "Extension Host": fetch `/api/nav`,
list remote-capable items (remoteEntry present) w/ badge tier + api version
(from manifest when available via future endpoint — for now display
EXTENSION_CONTRACT_VERSION const + item.tier), plus note pointing to
verify-publisher authority. Keep read-only.
Tests (new `tests/unit/console/test_extension_host_contracts.py`):
1. manifest validation — signed-valid passes, unknown capability violates
   (reuse RuntimeExtension.validate);
2. capability authorization — hostApisForTier('unsigned-local') ⊆
   READ_ONLY_HOST_APIS and excludes every TRUSTED entry;
3. host-API authorization — can() false for every name outside tier list
   (iterate ExtensionHostContext surface names);
4. failure isolation — RemoteErrorBoundary renders ExtensionLoadError when
   child throws (React test via testing-library if configured; else assert
   boundary class exists in App source? prefer jsdom-free: extract boundary
   into component test using react-test-renderer IF dep exists — check
   package.json; otherwise static-assert getDerivedStateFromError behavior
   via direct method call).

### 3.4 Endpoint-schema suite
New dir `spec/console-api/` + `tests/unit/console/test_gui_endpoint_schemas.py`.
Inline-or-file JSON Schemas for GET responses: `/api/runs`,
`/api/scenarios`, `/api/nav`, `/api/system/status`, `/v1/doctor`,
`/api/v1/metrics`, `/api/v1/agent-targets`, `/api/v1/evidence/packages`,
`/api/v1/certificates/<id>`. Harness pattern (mirror
test_console_routes_runs fixtures): register blueprint(s) on bare Flask app,
monkeypatch config paths, AGENTV_TEST_AUTH_BYPASS via conftest already set,
hit endpoint, jsonschema.validate. Add one test per endpoint; failures print
diff. Exit: 9 endpoints locked.

### 3.5 Quick-win tests (sketches ready)
a) Join-generation unit (append `test_workflow_interpreter.py`):
```python
def test_join_rejects_cross_iteration_tokens():
    from eval_runner.workflow_interpreter import ExecutionToken, _SchedulerState

    plan = _plan(
        {
            "workflow": {
                "nodes": [{"id": "j"}],
                "edges": [
                    {"id": "e1", "from": "a", "to": "j"},
                    {"id": "e2", "from": "b", "to": "j"},
                ],
                "entry_nodes": ["j"],
            }
        }
    )
    # direct _try_join needs plan.nodes['a']/'b' exist -> instead build 3-node graph
```
(adjust: use full a,b,j graph; craft state.pending_tokens manually with
ExecutionToken(edge_id='e1',branch_generation='g',produced_by='a:attempt:1',iteration=1)
and e2 iteration=9 → expect no activation; then iter=1 → activates.)
b) Timeout routing e2e (node `{"timeout": 0.05}`, executor sleeps 0.3):
assert outcome.success via timeout edge, record.timed_out True,
transitions[0].reason == 'timeout_route'.
c) Parallel timing: two 0.25s sleeps in one wave complete < 0.45s wall.
d) Consensus unit: patch `eval_runner.llm_providers.LLMProviderFactory.create`
and `eval_runner.metrics.MetricRegistry.get`; preset
`session._last_transition_expectations=['Done']`; cover majority-pass,
quorum-fail(evaluated False), unknown-strategy, ija INCONCLUSIVE.

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
bandit -ll -r .
npm run build --prefix ui/visual-console
npm run test:docmodel --prefix ui/visual-console
```
Last full sweep (user-run): 2988p/4f — the 4 are fixed locally; expect ~2996p.
Coverage gate 90% (was 94.54%).

## 6. Verify quickly anytime
```
python -m pytest tests/unit/core/test_workflow_interpreter.py tests/unit/core/test_vc_truth_level.py tests/unit/spec -q
python -m pytest tests/unit/handlers/test_catalog.py tests/unit/core/test_analyzer.py -q
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
