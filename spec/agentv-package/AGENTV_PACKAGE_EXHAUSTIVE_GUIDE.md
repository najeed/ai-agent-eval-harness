# AgentV Verification Package — Exhaustive Specification Guide

**Envelope:** `.agentv-package.json` · **Schema:** `agentv-package.schema.json` · **Version:** 2.0.0 (pinned to `agentv_runtime.versions.VERIFICATION_PACKAGE_VERSION`)

Companion specs: [`spec/vc/`](../vc/VC_SPEC_EXHAUSTIVE_GUIDE.md) (certificates) · [`spec/runs/`](../runs/RUNS_SPEC_EXHAUSTIVE_GUIDE.md) (run records) · [`spec/aes/`](../aes/AES_SCHEMA_EXHAUSTIVE_GUIDE_FINAL.md) (scenario documents).

---

## 1. Purpose & Trust Model

A Verification Package is the **single immutable artifact** an auditor receives after a run. It answers, without reconstructing anything from raw traces:

1. *What exactly was executed?* → `chain` (five-field provenance header)
2. *What did the agent do and did it pass?* → `verdict` + `evidence_manifest`
3. *Why should I believe it?* → `cryptographic_verification` + `evidence_graph`
4. *Can I reproduce it?* → `chain.resolved_config_hash` (+ scenario revision hash)
5. *Is this simulated or live?* → `chain.execution_mode` / `execution_mode_declared`

Trust invariants:

- The package is **content-addressed**: `package_hash` = SHA3-256 over `json.dumps(canonical_payload, sort_keys=True, separators=(',',':'))` where canonical payload excludes `package_hash` and `package_created_at`.
- Any mutation of trace content, verdicts, or chain invalidates `package_hash` and/or the certificate's `trace_hash` binding.
- A package can only be `VERIFIED` when the runtime's signature verifier proves both manifest-hash and scenario-hash match; corruption (`EVIDENCE_INVALID`) blocks certification regardless of signatures.

## 2. Envelope Map (every key)

| Key | Type | Req | Semantics |
|---|---|---|---|
| `format` | const | ✔ | `"agentv_verification_package"` |
| `package_version` | const | ✔ | `"2.0.0"`. Additive-only within 2.x. |
| `run_id` | string | ✔ | Globally-unique run id (UUIDv7-suffixed). |
| `tenant_id`, `workspace_id` | string | – | Multi-tenant labels from run manifest. |
| `chain` | object | ✔ | Five-field provenance header. |
| `manifest` | object | – | Persisted run manifest (certificate metadata). |
| `scenario` | object | – | Resolved AES document executed. |
| `verdict` | object | ✔ | Outcome literals. |
| `evidence_chain_valid` | bool | ✔ | `true` ⇔ outcome==VERIFIED ∧ no corruption. |
| `cryptographic_verification` | object | ✔ | Signature proof details. |
| `evidence_manifest` | object | ✔ | Trace hash, event/assertion counts, artifact hashes. |
| `evidence_graph` | object | ✔ | Assertion→event linkage. |
| `integrity_corruption` | object | ◆ | Present ONLY under `EVIDENCE_INVALID`; byte offsets of unparseable lines. |
| `signatures` | array | – | Certificate provenance chain (Ed25519 / ML-DSA-65 nodes). |
| `package_hash` | string | ✔ | Content address. |
| `package_created_at` | date-time | – | Envelope timestamp; excluded from hash. |

## 3. The Chain Header (five required bindings)

```json
"chain": {
  "run_id": "run-<scenario>-<uuid7hex>",
  "scenario_hash": "sha3_256:<64hex>",
  "resolved_config_hash": "sha3_256:<64hex>",
  "agent_target_id": "<identifier>",
  "execution_mode": "live",
  "execution_mode_declared": true
}
```

- `scenario_hash` — computed over the **resolved** scenario document actually executed (`compute_scenario_hash`). This is the revision identity; a path is never sufficient.
- `resolved_config_hash` — reproducibility fingerprint bound at `run_start`: executor version + IR version + evaluator-registry fingerprint + plugin provenance + adapter/provider + environment + seed + fixture hashes.
- `agent_target_id` — dispatch identifier for the agent endpoint/target used.
- `execution_mode` ∈ {simulated, record_replay, live, hybrid, unknown}. **`simulated` and `unknown` packages are non-authoritative for compliance claims.**
- `execution_mode_declared=false` ⇒ the mode was a silent default; consumers must treat the package as provisional.

## 4. Verdict Literals

`verdict.verified_outcome` ∈:

| Literal | Meaning |
|---|---|
| `VERIFIED` | Signature chain proved; manifest+scenario hashes match; no corruption. |
| `UNVERIFIED` | Execution passed but signature/hash proof failed. Never upgrade. |
| `NOT_VERIFIED` | Execution failed (or produced failure assertions). |
| `POLICY_BREACH` | Authoritative `policy_violation` event present — overrides all. |
| `EVIDENCE_INVALID` | Unparseable trace lines (see `integrity_corruption`). Overrides VERIFIED. |

## 5. Cryptographic Verification Block

Produced by the authoritative verifier (`verify_trace_certificate`), not by artifact presence: `verified`, `signer_identity`, `manifest_hash_match`, `scenario_hash_match`, `algorithm` (Ed25519 today; ML-DSA-65 via PQC chain), and `errors[]` listing every failed check. Partial verification is never represented as verified.

## 6. Evidence Graph

Each assertion row is linked to its exact source event by `_seq` plus a per-line content hash, or explicitly marked `UNRESOLVED`. Artifact hashes (`run.jsonl` → trace hash) anchor the graph to `evidence_manifest.artifacts`.

## 7. Validation

```bash
python - <<'PY'
import json, jsonschema
pkg = json.load(open("pkg.agentv-package.json"))
schema = json.load(open("spec/agentv-package/agentv-package.schema.json"))
jsonschema.validate(pkg, schema)
PY
```

Endpoint: `GET /api/v1/evidence/packages/<run_id>[?download=true]` returns a package conforming to this schema (contract-tested).

---

## Reference Walkthrough: VERIFIED Live-Run Package

```json
{
  "format": "agentv_verification_package",
  "package_version": "2.0.0",
  "run_id": "run-loan-auth-3f9c1e7a2b8d4f60a1c2d3e4f5a6b7c8",
  "tenant_id": "acme",
  "workspace_id": "lending-prod",
  "chain": {
    "run_id": "run-loan-auth-3f9c1e7a2b8d4f60a1c2d3e4f5a6b7c8",
    "scenario_hash": "sha3_256:7c1f…90ab",
    "resolved_config_hash": "sha3_256:41dd…77c0",
    "agent_target_id": "primary-agent",
    "execution_mode": "live",
    "execution_mode_declared": true
  },
  "manifest": { "vc_version": "3.0.0", "trace_hash": "sha3_256:0aa8…13de" },
  "scenario": { "aes_version": 1.4, "id": "loan_auth_flow" },
  "verdict": {
    "execution_status": "EXECUTION_COMPLETED",
    "verified_outcome": "VERIFIED",
    "duration_seconds": 18.42,
    "score": 1.0
  },
  "evidence_chain_valid": true,
  "cryptographic_verification": {
    "verified": true,
    "signer_identity": "runner-01",
    "manifest_hash_match": true,
    "scenario_hash_match": true,
    "algorithm": "ed25519",
    "errors": []
  },
  "evidence_manifest": {
    "trace_hash": "sha3_256:0aa8…13de",
    "total_events": 214,
    "assertions_evaluated": 6,
    "artifacts": [
      { "name": "run.jsonl", "hash": "sha3_256:0aa8…13de", "type": "trace_events" }
    ]
  },
  "evidence_graph": {
    "graph_version": "1.0.0",
    "node_count": 6,
    "resolved_count": 6,
    "unresolved_count": 0,
    "nodes": [
      {
        "kind": "success_criteria",
        "label": "exact_match",
        "node_id": "t1",
        "passed": true,
        "severity": "required",
        "invalid": false,
        "source_type": "trace_event",
        "source_ref": "run.jsonl#seq=209",
        "content_hash": "sha3_256:be44…11cf",
        "resolved": true,
        "row_hash": "sha3_256:9d07…52ea"
      }
    ],
    "evidence_root_hash": "sha3_256:e5b1…84f3"
  },
  "signatures": [
    {
      "identity": "runner-01",
      "role": "Evaluator",
      "signature": "ecc8…9902",
      "timestamp": "2026-08-25T10:15:00Z"
    }
  ],
  "package_hash": "sha3_256:c88e…01ba",
  "package_created_at": "2026-08-25T10:15:02Z"
}
```

Walkthrough notes:

- `chain` is the auditor's entry point: revision hash of the resolved
  scenario, the reproducibility fingerprint bound at `run_start`, the agent
  target identity, and an **operator-declared** live mode.
- `evidence_graph.nodes[]` is the truthful linkage contract: each assertion
  resolves to a trace line (`source_ref` + `content_hash`) or reports
  `resolved:false` — provenance is never invented. `evidence_root_hash`
  commits to the sorted set of per-node row hashes.
- Hash strings are elided here for readability; the schema enforces full
  `^sha3_256:[0-9a-f]{64}$` forms in real packages.
- A tampered trace flips `trace_hash`, breaks `manifest_hash_match`, and
  demotes the outcome to UNVERIFIED — the package still validates, but
  `evidence_chain_valid=false` tells the auditor why it must not be trusted.

### Contrast: EVIDENCE_INVALID variant

```json
"integrity_corruption": {
  "status": "EVIDENCE_INVALID",
  "corrupt_count": 1,
  "corrupt_line_byte_offsets": [40961],
  "policy": "Unparseable trace content detected; the evidence stream cannot be certified until the trace is intact."
}
```

Presence of this block forces `verified_outcome = EVIDENCE_INVALID` and
`evidence_chain_valid = false` regardless of signature validity.
