---
title: AgentV Tester Dependencies
description: Exact boundary and CI dependencies on the independent agentv-tester acceptance estate.
---

# AgentV Tester Dependencies

`agentv-tester` is an independent fixture/actor repository used only by
acceptance certification. AgentV Runtime, normal unit tests, package builds,
and ordinary product operation must not require it.

## Trust boundary

AgentV is the system under test. `agentv-tester` supplies independent actor
processes and an independently queryable state authority. Acceptance must not
derive an external-state result from AgentV traces or manifests when a tester
oracle is configured.

The OSS local AgentV artifact store remains cryptographically tamper-evident
and logically sealed; it is not the external state authority or WORM storage.

## Pinned CI dependency

The `acceptance-release` job in `.github/workflows/acceptance.yml` requires:

| Configuration | Meaning | Failure behavior |
| --- | --- | --- |
| `vars.AGENTV_TESTER_REPOSITORY` | Repository to check out | Release acceptance fails closed if absent. |
| `vars.AGENTV_TESTER_SHA` | Immutable commit SHA | Release acceptance fails closed if absent or unresolvable. |
| `secrets.AGENTV_TESTER_READ_TOKEN` | Read token for the tester repository | Release acceptance fails closed if absent. |
| `AGENTV_ACCEPTANCE_ORACLE_URL` | Local oracle URL passed to acceptance tests | Set by CI to `http://127.0.0.1:8099/acceptance-oracle`. |

CI checks out the tester repository at the requested SHA into
`.ci/agentv-tester`; it never uses a floating branch/tag. It launches the
minimal oracle entrypoint and health-checks it before release acceptance runs.
Checkout, startup, health-check, or receipt failures are release failures—no
trace-derived fallback is permitted.

## Required tester services

### State oracle

`server/run_acceptance_oracle.py` starts the minimal independent state
authority. It exposes:

| Endpoint | Purpose |
| --- | --- |
| `POST /acceptance-oracle/reset` | Establish pre-run balances. |
| `GET /acceptance-oracle/state` | Return state plus SHA3-256 observation receipt. |
| `POST /acceptance-oracle/transfers` | Commit an idempotent ledger transfer. |

Acceptance resets state before each oracle-backed case and compares the
declared expected final-state subset to the post-run oracle observation.

### Independent fixture actors

`server/acceptance_agents.py` provides deterministic, credential-free actor
boundaries for release fixtures:

| Endpoint | Actor responsibility |
| --- | --- |
| `POST /risk-agent/authorize` | Produce SHA3-bound ALLOW/BLOCK authorization. |
| `POST /payment-agent/transfer` | Require valid authorization, then commit to the oracle ledger. |
| `POST /approval-agent/decision` | Persist a SHA3-bound approval/rejection record. |
| `GET /document-agent/untrusted-transfer-request` | Serve a hashed untrusted injection payload. |

These endpoints are intentionally separate from AgentV’s trace, manifest,
certificate, and verifier implementation. They may be used by HTTP acceptance
scenarios, but not replaced with local AgentV simulators when validating
external state.

## Current consuming AgentV files

| AgentV location | Dependency |
| --- | --- |
| `.github/workflows/acceptance.yml` | Pinned checkout, oracle process, health check, environment URL. |
| `tests/acceptance/support/artifact_reader.py` | Reset/read external oracle observations. |
| `tests/acceptance/test_acceptance_corpus.py` | Resolves oracle URL, resets state, records post-run receipt/state. |
| `tests/acceptance/fixtures/agents/compliant_transfer_agent.py` | Commits only after AgentV's approved completion path. |
| `tests/acceptance/corpus/*/AT-*.yaml` | Declares oracle URL and expected external balances for migrated cases. |

## Non-dependencies

The following must continue to work without `agentv-tester`:

- `pytest tests/unit` and normal CI;
- runtime/console startup;
- wheel build and publication build stages;
- local development without acceptance-release enabled.

Only the protected release-acceptance job is authorized to require tester
credentials and the pinned external fixture estate.

