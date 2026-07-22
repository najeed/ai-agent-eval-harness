# VC Specification Masterclass: The forensic Chain of Custody

This guide provides an exhaustive inventory of the **AgentV Verification Certificate (VC)** specification (v3.0.0). The VC is the authoritative document that proves an evaluation's integrity, provenance, and compliance status.

---

## 🏗️ The Chain of Custody Philosophy

In industrial AI evaluation, a "Result" is only as good as the proof that it hasn't been tampered with. The VC serves as a **Cryptomark** on the dataset, ensuring that:
1.  **Immutability**: The raw trace (`run.jsonl`) has not been altered.
2.  **Atomicity**: Every sidecar artifact (logs, snapshots) is anchored to the run.
3.  **Non-Repudiation**: Stakeholders (Evaluators, Auditors) have digitally signed the outcome.

---

## Lesson 1: The Integrity Core (SHA-256 & Vaulting)

The VC uses **SHA-256** hashing to create a unique fingerprint for every artifact in the session vault.

### 1. The Master Trace Hash (`sha256`)
The top-level `sha256` property is the hash of the core `run.jsonl` file. 
> **Verification Protocol**: Any tool verifying the certificate MUST recalculate the hash of the trace file and compare it to this field. A single bit difference in the trace will cause a verification failure.

### 2. The Trace Context (`harness_version` & `trace_file`)
To ensure forensic portability, the VC explicitly declares its runtime context:
- **`harness_version`**: The exact version of the AgentV engine that generated the trace and certificate.
- **`trace_file`**: The basename of the primary trace file (usually `run.jsonl`).

### 3. The Evidence Ledger (`evidence_ledger`)
Sidecars (Database snapshots, terminal outputs, screenshots) are listed in a map:
- **Keys**: The relative path within the session vault (e.g., `forensics/db_snapshot.sqlite`).
- **Values**: The 64-character SHA-256 hex hash of that file.

---

## Lesson 2: The Provenance Chain (Ed25519 Multi-Sig)

AgentV uses the **Ed25519** (RFC 8032) signature algorithm. This is faster and more secure than RSA or ECDSA for forensic logging.

### 1. Signature Schema
The `provenance_chain` is an array of signature objects:
| Field | Type | Purpose |
| :--- | :--- | :--- |
| `identity` | String | The ID of the signer (resolved via `IdentityService`). |
| `timestamp` | Date-Time | The ISO-8601 moment the signature was generated. |
| `signature` | String | The hex-encoded Ed25519 digital signature. |
| `role` | Enum | The stakeholder's authority level: `Agent`, `Evaluator`, `Auditor`. |

### 2. Multi-Party Signing Lifecycle
1.  **Stage 1: Self-Certification**: The evaluation runner automatically signs the VC as the `Evaluator`.
2.  **Stage 2: Agent Commitment**: Advanced agents can sign the VC with their private key to "agree" with the recorded trace.
3.  **Stage 3: Peer/Auditor Review**: In high-stakes fintech scenarios, a human or automated auditor adds a third signature after reviewing the forensics.

---

## Lesson 3: Compliance & Expiration Lifecycle

### 1. Compliance Anchoring
The `compliance` block anchors the result to an industrial policy:
- **`score`**: The WSM aggregate score (0.0 to 1.0).
- **`status`**: The final verdict (`pass`, `fail`, `warning`, `error`).
- **`policy_ref`**: The semantic link to the standard (e.g., `NIST-AI-100-1-v1.4`).

### 2. The Expiration Protocol (`governance_ttl`)
Digital certificates are not eternal. The `governance_ttl` (in days) defines the certificate's validity window.
- **Verification Logic**: If `timestamp` + `governance_ttl` < `current_time`, the VC status is downgraded to `STALE`.
- **Re-certification**: Stale certificates require a re-audit or re-run of the evaluation to maintain compliance status.

---

## Reference Walkthrough: Triple-Signed Audit Certificate

```json
{
  "vc_version": "3.0.0",
  "harness_version": "1.5.0",
  "run_id": "audit-fc-2026-001",
  "trace_file": "run.jsonl",
  "sha256": "8f02...e9a1",
  "compliance": {
    "status": "pass",
    "score": 0.94,
    "policy_ref": "FINTECH-SEC-v3"
  },
  "evidence_ledger": {
    "forensics/ledger_audit.log": "dc01...ff02",
    "forensics/db_init.sql": "ba01...ee02"
  },
  "provenance_chain": [
    {
      "identity": "runner-01",
      "role": "Evaluator",
      "signature": "ecc8...9902",
      "timestamp": "2026-04-12T03:55:00Z"
    },
    {
      "identity": "agent-loan-gpt-5.4-mini",
      "role": "Agent",
      "signature": "887a...11bc",
      "timestamp": "2026-04-12T03:55:05Z"
    }
  ],
  "governance_ttl": 365
}
```
