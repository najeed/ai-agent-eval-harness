# API Reference (Programmatic Authorization)

This document provides a technical guide for interacting with the Advanced AgentEval Harness REST API using specialized service keys.

## Authentication

Programmatic access is controlled via the `X-Api-Key` header.

### Provisioning
To enable headless access for Enterprise CI/CD pipelines:
1. Define a `SERVICE_API_KEY` in your environment.
2. If `SERVICE_API_KEY` is not defined, the harness will fallback to `DASHBOARD_API_KEY` for compatibility.

```bash
# Example environment setup
export SERVICE_API_KEY="aeh_service_prod_sha256_pk_..."
```

## Endpoints

### 1. Trigger Evaluation
`POST /api/evaluate`

Triggers an evaluation of a specific scenario in a background thread.

**Headers:**
- `X-Api-Key`: `{SERVICE_API_KEY}`
- `Content-Type`: `application/json`

**Body:**
```json
{
  "path": "industries/fintech/scenarios/loan_decision.yaml",
  "max_turns": 10
}
```

**Response (202 Accepted):**
```json
{
  "status": "started",
  "message": "Evaluation started for loan_decision.yaml",
  "scenario_id": "fin_loan_001"
}
```

### 2. Verify Run (Public)
`GET /api/v1/verify/<run_id>`

Public endpoint that verifies a completed run against its industrial manifest.

---

## Polling Pattern (CLI Integration)

For headless CI/CD, use the following pattern:
1. POST to `/api/evaluate`
2. Poll the report directory for the generated `aggregated_results.json` or `run.jsonl`.
3. Verify the run using the `multiagent-eval verify` CLI tool for industrial gating.
