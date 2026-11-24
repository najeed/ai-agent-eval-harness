---
title: Integrator API Reference
description: High-fidelity REST protocol for the AgentV Roadmap (v1.6.0+).
---

The Console API is mounted under `/api`. Authenticate with a verified session or
credentials accepted by the configured provider (for static service keys, use
`X-Api-Key`). Protected reads also require authentication and resource permission.

## Active scope

Principal entitlements are provider-owned. `AuthPrincipal` can carry
`context_version`, `context` and `authorized_contexts`; the active ScopePolicy
resolves a ScopeToken. Scope tags and their digest bind run/approval ownership.
Client body/query tenant labels cannot authorize a different scope.

## Mutations

`GET /api/v1/mutations` returns installed descriptors plus delivery capabilities.
Organization filtering comes from the authenticated active context; `?org_id=`
does not choose the catalog tenant.

`POST /api/v1/mutate` accepts `type`, optional `seed`, and one of `scenario_id`,
`input_path`, or `raw_json`, plus supported vector-specific options. Its result
is scenario generation (`delivery_status: "NOT_EXECUTED"`) with a lint report.
Executing a variant and proving fault delivery are separate steps.

## Preflight and launch

`POST /api/scenarios/readiness` accepts the scenario path/ID and execution
configuration. It returns `ready`, `is_executable`, `is_verifiable`,
`readiness_state`, checks and a `preflight_fingerprint` bound to the configuration.
Use the same configuration and fingerprint with `POST /api/v1/evaluate`.
Production and `EVAL_REQUIRE_PREFLIGHT=true` enforce that binding.

Launch returns `run_id` and manifest identifiers. Poll
`GET /api/v1/runs/<run_id>` or subscribe to
`GET /api/v1/runs/<run_id>/stream`. SSE reconnects with `Last-Event-ID`; use session
credentials rather than embedding tokens in the stream URL.

## Export and verification

`GET /api/v1/evidence/packages/<run_id>?download=true` exports the console wrapper.
It includes the scenario/manifest views and signed typed verification package;
it does not replace the provider's exact raw trace bytes.

`POST /api/v1/evidence/verify` requires:

- `package`: signed package or supported export wrapper;
- `raw_trace_bytes`: base64 of the actual committed JSONL bytes;
- `execution_manifest`: the actual execution manifest;
- `scenario_data`: the executed scenario contract.

Trust keys/policy are resolved server-side. The authoritative endpoint rejects
caller `public_key_pem`, reconstructed `raw_trace_events`, and
`require_signature: false`. Signature/oracle/manifest/scenario/finalization
checks must all succeed for an authoritative verdict. Invalid inputs are not
silently downgraded to authoritative success.

Use `POST /api/v1/evidence/verify-diagnostic` for explicit diagnostic analysis.
Its result cannot certify a run. `GET /api/v1/runs/<run_id>/verify` additionally
checks provider-owned sealed lifecycle state. See
[cryptographic verification](/auditor/verification/) for complete examples.

## Other endpoints

`GET /api/v1/metrics`, `/api/v1/taxonomy`, `/api/v1/doctor`, and
`/api/v1/explain/<run_id>` expose discovery and diagnostic services.
`POST /api/v1/spec-to-eval` accepts `markdown` content or `input_path`.
`GET /api/scenarios`, `POST /api/scenarios` and `GET /api/info` support catalog
and management workflows. Scenario updates accept `expected_revision_hash` and
reject conflicting writes with 409. Consult the
[Extender API](/extender/api-reference/) for lifecycle transitions and certificate
routes.
