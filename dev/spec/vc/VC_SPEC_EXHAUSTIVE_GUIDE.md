# VC Specification Masterclass: The Forensic Chain of Custody

This guide provides an exhaustive inventory of the **AgentV Verification Certificate (VC)** specification (v3.0.0). The VC is the authoritative document that proves an evaluation's integrity, provenance, and compliance status.

---

## 🏗️ The Chain of Custody Philosophy

In industrial AI evaluation, a "Result" is only as good as the proof that it hasn't been tampered with. The VC serves as a **Cryptomark** on the dataset, ensuring that:
1.  **Immutability**: The raw trace (`run.jsonl`) has not been altered.
2.  **Atomicity**: Every sidecar artifact (logs, snapshots) is anchored to the run.
3.  **Non-Repudiation**: Stakeholders (Evaluators, Auditors) have digitally signed the outcome using standard Ed25519 or Post-Quantum (ML-DSA-65) signatures.

---

## Lesson 1: The Integrity Core (SHA3-256 & Vaulting)

The VC uses **SHA3-256** hashing to create a unique fingerprint for every artifact in the session vault.

### 1. The Master Trace Hash (`trace_hash`)
The top-level `trace_hash` property is the hash of the core `run.jsonl` file. 
> **Verification Protocol**: Any tool verifying the certificate MUST recalculate the hash of the trace file and compare it to this field. A single bit difference in the trace will cause a verification failure. The algorithm is defined by `hash_algorithm` (default `sha3_256`).

### 2. The Trace Context (`harness_version` & `trace_file`)
To ensure forensic portability, the VC explicitly declares its runtime context:
- **`harness_version`**: The exact version of the AgentV engine that generated the trace and certificate (e.g., `2.0.0`).
- **`trace_file`**: The basename of the primary trace file (usually `run.jsonl`).

### 3. The Evidence Ledger (`evidence_ledger`)
Sidecars (Database snapshots, terminal outputs, screenshots) are listed in a map:
- **Keys**: The relative path within the session vault (e.g., `forensics/db_snapshot.sqlite`).
- **Values**: The 64-character SHA3-256 hex hash of that file.

---

## Lesson 2: The Provenance Chain (Ed25519 & Post-Quantum Multi-Sig)

AgentV uses **Ed25519** (RFC 8032) and **ML-DSA-65** (NIST FIPS 204 Post-Quantum Cryptography). This provides high-throughput signing with quantum-resistant long-term non-repudiation for regulatory audit archives.

### 1. Signature Schema
The `provenance_chain` is an array of signature objects:
| Field | Type | Purpose |
| :--- | :--- | :--- |
| `identity` | String | The ID of the signer (resolved via `IdentityService` or KMS/HSM). |
| `timestamp` | Date-Time | The ISO-8601 moment the signature was generated. |
| `signature` | String | The hex-encoded Ed25519 or ML-DSA digital signature. |
| `role` | Enum | The stakeholder's authority level: `Agent`, `Evaluator`, `Auditor`. |

### 2. Multi-Party Signing Lifecycle
1.  **Stage 1: Self-Certification**: The evaluation runner automatically signs the VC as the `Evaluator` using the local or KMS signing backend.
2.  **Stage 2: Agent Commitment**: Advanced agents sign the VC with their identity key to cryptographically commit to the recorded trajectory.
3.  **Stage 3: Peer/Auditor Review**: In high-stakes fintech, aerospace, or clinical scenarios, an independent auditor appends a third signature after completing forensic verification.

---

## Lesson 3: Compliance & Expiration Lifecycle

### 1. Compliance Anchoring
The `compliance` block anchors the result to an industrial policy:
- **`score`**: The WSM aggregate score (0.0 to 1.0).
- **`status`**: The final verdict (`pass`, `fail`, `warning`, `error`).
- **`policy_ref`**: The semantic link to the standard (e.g., `NIST-AI-100-1-v1.4`, `EU-AI-ACT-HIGH-RISK`).

### 2. The Expiration Protocol (`governance_ttl`)
Digital certificates are not eternal. The `governance_ttl` (in days) defines the certificate's validity window.
- **Verification Logic**: If `timestamp` + `governance_ttl` < `current_time`, the VC status is downgraded to `STALE`.
- **Re-certification**: Stale certificates require a re-audit or re-run of the evaluation to maintain compliance status.

---

## Lesson 4: The Truth Level (`execution_mode` & `provisional`)

Every certificate **must** state the execution truth level of its run. This field is REQUIRED in `vc.schema.json`.

| Field | Type | Semantics |
| :--- | :--- | :--- |
| `execution_mode` | Enum (required) | `simulated` \| `record_replay` \| `live` \| `hybrid` \| `unknown`. Simulated/unknown certificates are **non-authoritative for compliance claims**. |
| `provisional` | Boolean (optional) | `true` when the mode was never explicitly declared by the operator (silent SIMULATED default) or could not be determined from the vault. Provisional certificates must never back audit claims; TrustCenter and RunDetailView surface them as such. |

**Producer contract:**
- `TraceVerifier.sign_trace()` stamps the field unconditionally. When the run vault provides no declaration, it stamps `"unknown"` + `provisional: true` — truthful absence, never fabricated as `simulated`.
- The certification REST path reads the run's `run_start` event (`execution_mode`, `execution_mode_declared`) and logs a loud WARNING whenever a provisional certificate is issued.
- Sessions that silently default to SIMULATED print an unmistakable double-warning banner and record `execution_mode_declared=false` on `run_start`, so declared-vs-defaulted provenance is preserved forever.

> **Validation impact**: manifests produced before this hardening fail schema validation until re-certified. This is intentional fail-closed adoption.

---

## Reference Walkthrough: Triple-Signed Audit Certificate

```json
{
  "vc_version": "3.0.0",
  "harness_version": "2.0.0",
  "run_id": "audit-fc-2026-001",
  "trace_file": "run.jsonl",
  "trace_hash": "8f020188bc8a9012cd34ef5678901234567890abcdef1234567890abcdef9012",
  "hash_algorithm": "sha3_256",
  "execution_mode": "live",
  "compliance": {
    "status": "pass",
    "score": 0.94,
    "policy_ref": "NIST-AI-100-1-WSM"
  },
  "evidence_ledger": {
    "forensics/ledger_audit.log": "dc0188bc8a9012cd34ef5678901234567890abcdef1234567890abcdef9012",
    "forensics/db_init.sql": "ba0188bc8a9012cd34ef5678901234567890abcdef1234567890abcdef9012"
  },
  "provenance_chain": [
    {
      "identity": "runner-01",
      "role": "Evaluator",
      "signature": "ecc8776655443322110099887766554433221100998877665544332211009902",
      "timestamp": "2026-08-25T12:00:00Z"
    },
    {
      "identity": "agent-loan-gpt-5.6",
      "role": "Agent",
      "signature": "887a11bc22cd33de44ef55fa66bc77de88fa99bc00cd11de22fa33bc44de55bc",
      "timestamp": "2026-08-25T12:00:05Z"
    }
  ],
  "governance_ttl": 365,
  "provisional": false
}
```
