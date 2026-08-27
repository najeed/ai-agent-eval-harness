# VC Specification Masterclass: The Forensic Chain of Custody

This guide provides an exhaustive inventory of the **AgentV Verification Certificate (VC)** specification (`v3.0.0`, schema at [`spec/vc/vc.schema.json`](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/spec/vc/vc.schema.json)). The VC is the authoritative cryptographic document that proves an evaluation's integrity, provenance, multi-judge consensus, and compliance status.

---

## 🏗️ The Chain of Custody Philosophy

In industrial AI evaluation, a "Result" is only as good as the proof that it hasn't been tampered with. The VC serves as a **Cryptomark** on the dataset, ensuring that:
1. **Immutability**: The raw trace (`run.jsonl`) has not been altered (`trace_hash` via SHA3-256).
2. **Atomicity**: Every sidecar artifact (logs, snapshots, databases) is anchored in the `evidence_ledger`.
3. **Epistemic Truth**: Multi-judge consensus agreements and rubric scores are cryptographically bound to the certificate, not self-attested post-hoc flags.
4. **Non-Repudiation**: Stakeholders (Evaluators, Auditors, Autonomous Agents) digitally sign the outcome using standard Ed25519 or Post-Quantum (ML-DSA-65) signatures.

---

## Lesson 1: The Integrity Core (SHA3-256 & Vaulting)

The VC uses **SHA3-256** hashing to create an immutable fingerprint for every artifact in the session vault.

### 1. The Master Trace Hash (`trace_hash`)
The top-level `trace_hash` property is the SHA3-256 digest of the primary `run.jsonl` trace file. 
> **Verification Protocol**: Any tool verifying the certificate MUST recalculate the SHA3-256 hash of the trace file and compare it to this field. A single bit difference in the trace will cause a cryptographic verification failure.

### 2. The Trace Context (`harness_version` & `trace_file`)
To ensure forensic portability, the VC explicitly declares its runtime context:
- **`harness_version`**: The exact version of the AgentV engine that generated the trace and certificate (e.g., `2.0.0`).
- **`trace_file`**: The basename of the primary trace file (usually `run.jsonl`).

### 3. The Evidence Ledger (`evidence_ledger`)
Sidecars (database snapshots, terminal outputs, screenshots, state dumps) are listed in an exact map:
- **Keys**: Relative file path within the session vault (e.g., `forensics/db_snapshot.sqlite`).
- **Values**: 64-character SHA3-256 hexadecimal hash of that file.

### 4. The Evidence Root Hash (`evidence_root_hash`)
Additive field committing to the Merkle root hash of the decision's complete assertion and oracle set, proving that every success criterion and state invariant was evaluated.

---

## Lesson 2: The Provenance Chain (Ed25519 & Post-Quantum Multi-Sig)

AgentV supports **Ed25519** (RFC 8032) and **ML-DSA-65** (NIST FIPS 204 Post-Quantum Cryptography). This provides high-throughput signing with quantum-resistant long-term non-repudiation for regulatory audit archives.

### 1. Signature Schema
The `provenance_chain` is an array of signature objects:
| Field | Type | Purpose |
| :--- | :--- | :--- |
| `identity` | String | The ID of the signer (resolved via `IdentityService` or KMS/HSM). |
| `timestamp` | Date-Time | The ISO-8601 moment the signature was generated. |
| `signature` | String | The hex-encoded Ed25519 or ML-DSA digital signature. |
| `role` | Enum | The stakeholder's authority level: `Agent`, `Evaluator`, `Auditor`. |

### 2. Multi-Party Signing Lifecycle
1. **Stage 1: Evaluator Attestation**: The runtime certification pipeline (`TraceVerifier.sign_trace`) signs the VC as the `Evaluator`.
2. **Stage 2: Agent Non-Repudiation**: The evaluated autonomous agent signs the VC with its key to cryptographically commit to the recorded trajectory.
3. **Stage 3: Auditor Verification**: In regulated fintech, aerospace, or clinical scenarios, an independent auditor appends a third signature after completing forensic verification.

---

## Lesson 3: Compliance & Expiration Lifecycle

### 1. Compliance Anchoring
The `compliance` block anchors the result to an industrial policy:
- **`score`**: The Weighted Severity Model (WSM) aggregate score (0.0 to 1.0).
- **`status`**: The final verdict (`pass`, `fail`, `warning`, `error`).
- **`policy_ref`**: The semantic link to the standard (e.g., `NIST-AI-100-1-v1.4`, `EU-AI-ACT-HIGH-RISK`, `FINRA-FIDUCIARY-RULE-2111`).

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
| `provisional` | Boolean (optional) | `true` when the mode was never explicitly declared by the operator (silent SIMULATED default) or could not be determined from the vault. Provisional certificates must never back audit claims. |

**Producer Contract:**
- `TraceVerifier.sign_trace()` stamps the field unconditionally. When the run vault provides no declaration, it stamps `"unknown"` + `provisional: true` — truthful absence, never fabricated as `simulated`.
- The certification REST path reads the run's `run_start` event (`execution_mode`, `execution_mode_declared`) and logs a loud WARNING whenever a provisional certificate is issued.

---

## Lesson 5: Multi-Judge Consensus & Fiduciary Rubrics (`consensus` & `rubrics`)

Industrial compliance packs gate on genuine judge consensus and qualitative fiduciary rubrics. The VC explicitly seals these outputs so auditors never have to rely on self-attested scores.

### 1. Multi-Judge Consensus (`consensus`)
Captures the output of multi-agent or multi-model evaluation panels:
- **`strategy`**: The consensus algorithm used (`Majority_Vote`, `Absolute_Unanimity`, `Weighted_Average`).
- **`min_judges`**: The minimum quorum threshold required to reach a binding verdict.
- **`agreement`**: The mathematical inter-judge agreement score (0.0 to 1.0). Gated directly by `ija_threshold` compliance checks.
- **`judge_votes`**: Granular breakdown of individual judge assessments and reasoning.

### 2. Qualitative Rubrics (`rubrics`)
Captures domain-specific rubric evaluations executed during the evaluation:
- Maps rubric dimensions (e.g. `fiduciary_accuracy`, `anti_hallucination`, `grounding_fidelity`) to resolved scores (0.0 to 1.0).
- Gated directly by `rubric_required` compliance pack checks.

---

## Reference Walkthrough: Fully Sealed Audit Certificate (VC v3.0.0)

```json
{
  "vc_version": "3.0.0",
  "harness_version": "2.0.0",
  "run_id": "audit-finra-2026-0828",
  "trace_file": "run.jsonl",
  "trace_hash": "8f020188bc8a9012cd34ef5678901234567890abcdef1234567890abcdef9012",
  "hash_algorithm": "sha3_256",
  "execution_mode": "live",
  "provisional": false,
  "evidence_root_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "compliance": {
    "status": "pass",
    "score": 0.96,
    "policy_ref": "FINRA-RULE-2111-SUITABILITY"
  },
  "consensus": {
    "strategy": "Majority_Vote",
    "min_judges": 3,
    "agreement": 0.92,
    "judge_panel": ["Luna-1", "Claude-3.7-Auditor", "GPT-5-Compliance"]
  },
  "rubrics": {
    "fiduciary_accuracy": 0.94,
    "grounding_fidelity": 0.98,
    "policy_adherence": 0.95
  },
  "evidence_ledger": {
    "forensics/ledger_audit.log": "dc0188bc8a9012cd34ef5678901234567890abcdef1234567890abcdef9012",
    "forensics/db_init.sql": "ba0188bc8a9012cd34ef5678901234567890abcdef1234567890abcdef9012"
  },
  "provenance_chain": [
    {
      "identity": "runner-01.eval.corp.internal",
      "role": "Evaluator",
      "signature": "ecc8776655443322110099887766554433221100998877665544332211009902",
      "timestamp": "2026-08-28T04:00:00Z"
    },
    {
      "identity": "agent-fiduciary-advisor-v2",
      "role": "Agent",
      "signature": "887a11bc22cd33de44ef55fa66bc77de88fa99bc00cd11de22fa33bc44de55bc",
      "timestamp": "2026-08-28T04:00:05Z"
    },
    {
      "identity": "auditor-pqc-seal.sec.gov",
      "role": "Auditor",
      "signature": "ab12cd34ef5678901234567890abcdef1234567890abcdef1234567890abcdef",
      "timestamp": "2026-08-28T04:01:00Z"
    }
  ],
  "governance_ttl": 365,
  "metadata": {
    "tenant_id": "enterprise-fintech",
    "workspace_id": "wealth-management-prod"
  }
}
```
