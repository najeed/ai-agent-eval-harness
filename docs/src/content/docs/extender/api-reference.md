---
title: Extender API Reference
description: Authoritative reference for the AgentV Console REST API and internal core libraries.
---

Launch the Flask API with `agentv console` (default `http://localhost:5000`).
Management routes use `/api`; possession of a run ID grants no access to another
scope. See [security](/auditor/security/) for the authentication boundary.

## Authentication and scope

`POST /api/auth/login` accepts `{"apiKey": "YOUR_KEY"}` and establishes a signed
Flask session. Cookies are HttpOnly, SameSite=Lax and Secure in production; they
are signed, not encrypted. Failed logins are rate-limited. Use `X-Api-Key` for
headless access, or a bearer credential accepted by the configured auth provider.
Protected scenario/run reads also require authentication; an anonymous Viewer
label in the UI does not grant API permissions.

The authenticated provider supplies context/authorized contexts. ScopePolicy
resolves the active ScopeToken; routes use that scope for provider reads and
mutations. Body/query tenant fields cannot grant ownership.

`POST /api/auth/handoff` issues a short-lived audience/plugin-bound identity token.
It carries normalized principal/context claims, not scenario execution state.
SSE uses the same-origin session and Last-Event-ID; do not put credentials into
stream URLs.

## Scenario and execution routes

| Method and route | Request or behavior |
| --- | --- |
| `GET /api/scenarios` | Catalog search and filters |
| `POST /api/scenarios` | AES scenario, or `scenario` plus `expected_revision_hash`; conflicts return 409 |
| `POST /api/scenarios/readiness` | JSON scenario path/ID and execution configuration; returns readiness checks and `preflight_fingerprint` |
| `POST /api/scenarios/<id>/transition` | `target_status` plus `reason` for sensitive transitions |
| `POST /api/v1/evaluate` | `path`, execution configuration and matching preflight fingerprint where required |
| `GET /api/runs` | Active scoped provider run listing |
| `GET /api/v1/runs/<id>` | Provider-owned execution record and status |
| `GET /api/v1/runs/<id>/stream` | SSE, with Last-Event-ID catch-up |
| `POST /api/v1/runs/<id>/cancel` | Cancel an authorized active run |
| `POST /api/v1/runs/<id>/resume` | Resume through the execution backend and approval checks |

The lifecycle transition body uses state values, not verb aliases:

```json
{"target_status": "Published", "reason": "Reviewed the validated release"}
```

Legal transitions are Draft→Validated/Deprecated,
Validated→Ready/Draft/Deprecated, Ready→Published/Deprecated, and
Published→Deprecated. Deprecated is terminal. Publication, regression to Draft,
and deprecation require a nonempty audit reason.

Evaluation dispatch uses `ExecutionBackend.submit(background=True)`, not a fixed
thread implementation. Production or `EVAL_REQUIRE_PREFLIGHT=true` requires the
matching preflight fingerprint. The normal response is HTTP 200 with `run_id`,
`manifest_id`, scenario revision and manifest data. The provider reserves and
tracks submission before dispatch. No filesystem or master-log fallback supplies
evidence to these read APIs.

## Trust and evidence

| Method and route | Behavior |
| --- | --- |
| `POST /api/v1/certify` | Certify an eligible run using the server-configured signer |
| `GET /api/v1/certificates/<id>` | Protected complete certificate view |
| `GET /api/v1/certificates/<id>/public` | Public projection, subject to actual certificate validity |
| `GET /api/v1/verify/<id>` | Public verification view |
| `GET /api/v1/identity/<id>/public_key` | Public key resolution |
| `GET /api/v1/runs/<id>/verify` | Provider-native run verification |
| `GET /api/v1/evidence/packages/<id>` | Console export wrapper; `?download=true` returns an attachment |
| `POST /api/v1/evidence/verify` | Authoritative package verification with server-owned trust |
| `POST /api/v1/evidence/verify-diagnostic` | Explicit non-authoritative analysis |

Certification accepts `run_id`, optional `policy_ref` and `ttl` in **days**.
Signing identity comes from `AES_CERTIFICATION_IDENTITY`; a caller identity does
not select a private key. Status/score are derived from evidence rather than
caller overrides. Execution completion does not automatically issue a certificate.

Authoritative evidence verification requires a `package`, base64
`raw_trace_bytes`, actual `execution_manifest` and `scenario_data`. It rejects
caller-supplied `public_key_pem`, reconstructed `raw_trace_events` and disabling
signature checks. Missing/invalid evidence returns an unverified response (422),
not an authoritative success. See [verification](/auditor/verification/) for
signature-only versus complete authority checks.

## Discovery and authoring

`GET /api/info`, `/api/nav`, `/api/v1/metrics`, `/api/v1/taxonomy`,
`/api/v1/doctor`, and `/api/v1/explain/<run_id>` expose the corresponding scoped
runtime views. `POST /api/v1/spec-to-eval` accepts Markdown content or an input
path. `GET /api/v1/mutations` uses organization scope from authenticated context;
`?org_id=` cannot select a tenant. `POST /api/v1/mutate` accepts `type` plus
`scenario_id`, `input_path`, or `raw_json` and returns a generated variant with
`delivery_status: "NOT_EXECUTED"`. Generation is not proof of executed faults.

## Python APIs

```python
from agentv_runtime.canonical import canonical_json_dumps, canonical_json_encode
from agentv_runtime.config import ConfigResolver
from agentv_runtime.contracts import MutationCoordinate, MutationDescriptor
from eval_runner.engine import run_evaluation
from eval_runner.mutations.mutator import sequence, repeat, probability, after_event

resolved = ConfigResolver.resolve(overrides={"timeout_seconds": 180})
payload_bytes = canonical_json_encode({"b": 1, "a": 2})
```

Execution signature:

```python
async def run_evaluation(scenario, run_id=None, attempts=1, seed=None, metadata=None, max_turns=None):
    ...
```

Use keywords when calling it. Single-attempt execution retains the first-result
compatibility return; multi-attempt execution returns attempt results.

Compose installed mutators as `sequence(mutator_a, mutator_b)`,
`probability(mutator_a, p=0.5)` and `after_event(mutator_b, "tool_result")`.
`concurrent` is reserved and raises an unsupported-delivery error.

Configuration precedence is defaults, files, supported environment overrides,
then explicit `overrides`, subject to configured mandates. Environment keys are
explicitly supported names such as `RUN_TIMEOUT_SECONDS` and `AUDIT_LEVEL`, not
arbitrary AGENTV_/AEH_ prefixes. Use detailed resolution diagnostics to detect
unknown keys. See [extension families](/extender/extension-families/) for complete
storage/signing/approval contracts, and [LLM providers](/builder/providers/) for
retry/error interfaces.
