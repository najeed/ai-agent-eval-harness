---
title: Cryptographic Verification & CI/CD Gating
description: Comprehensive verification workflows, server-authoritative endpoints, and automated CI/CD gating.
---

The **AgentV Verification Subsystem** provides mathematical, tamper-evident proof that evaluation runs executed authentically and achieved their required criteria.

---

## 🔬 1. Server-Authoritative Verification Endpoint

The Visual Console and external auditing systems verify runs by querying the authoritative backend verification endpoint:

```http
GET /api/v1/runs/{run_id}/verify HTTP/1.1
Host: localhost:5000
```

### Verification Evaluation Logic:
The backend executes `TraceVerifier.verify_run_directory()`, performing a 5-point cryptographic check:

```mermaid
graph TD
    V1["1. Read run.jsonl byte stream & compute SHA3-256"] --> V2["2. Validate trace_hash against run_manifest.json"]
    V2 --> V3["3. Recompute historical seal_hash against trace anchor"]
    V3 --> V4["4. Validate every artifact in evidence_ledger against disk"]
    V4 --> V5["5. Verify Ed25519 / PQC (ML-DSA) signature using IdentityService public key"]
    V5 --> PASS["Verification Status: VERIFIED"]
```

### Response Schema:
```json
{
  "run_id": "run_fintech_2026_01",
  "verification_status": "VERIFIED",
  "is_valid": true,
  "algorithm": "ML-DSA-65+Ed25519",
  "is_pqc": true,
  "signer_identity": "system_id",
  "trace_hash": "a8f94e2b...",
  "seal_hash": "e3b0c442...",
  "evidence_count": 4,
  "failure_reason": null
}
```

---

## 💻 2. CLI Offline Verification (`agentv verify`)

Audit execution traces directly on disk without launching the web server:

```bash
# Standard classical verification
agentv verify --run-id run_fintech_2026_01

# Post-quantum hybrid verification
agentv verify --run-id run_fintech_2026_01 --pqc
```

---

## 🚦 3. CI/CD Hard Gating (`agentv gate`)

The `agentv gate` command acts as a non-bypassable quality gate for deployment pipelines.

```bash
# GitHub Actions / GitLab CI Step
agentv gate \
  --run-id $RUN_ID \
  --verify-ledger \
  --pqc
```

### Exit Codes:
- `0`: Run is cryptographically authentic, ledger is complete, and all required assertions passed.
- `1`: Tamper detected, signature invalid, or failure criteria violated.

---

## 🌐 4. Framework Adapter Verification Matrix

Verify connectivity and readiness across target frameworks:

```bash
# AG2 (AutoGen)
agentv run --path scenarios/loan_risk.json --protocol ag2

# LangGraph
agentv run --path scenarios/loan_risk.json --protocol langgraph --agent http://localhost:8000/execute_task

# CrewAI
agentv run --path scenarios/loan_risk.json --protocol crewai --agent http://localhost:8000/execute_task

# Frontier Model Direct Adapters
agentv run --protocol gemini --agent "gemini://gemini-3.7-flash"
agentv run --protocol claude --agent "claude://claude-opus-5"
agentv run --protocol openai --agent "openai://gpt-5.6"
agentv run --protocol ollama --agent "ollama://deepseek-r1:70b"
```
