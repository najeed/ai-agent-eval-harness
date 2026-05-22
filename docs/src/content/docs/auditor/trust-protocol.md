---
title: Trust Protocol Standard
description: The industrial standard for non-repudiable evaluation traces and forensic integrity.
---

The Trust Protocol (v1.6.0) provides **immutable proof of run integrity** for the AgentV Harness. It employs a "Detached Signature" architecture that separates bulky execution data from metadata certificates.

## 1. Forensic Architecture

AgentV uses a tiered approach to ensure that evaluation results are authentic and tamper-proof.

```mermaid
graph TD
    A[Trace File .jsonl] -->|SHA-256| B[Content Hash]
    B --> C[Manifest v3 Metadata]
    S[Artifact Sidecars] -->|SHA-256| L[Evidence Ledger]
    L --> C
    D[Private Key] -->|Identity Sign| E[Verification Certificate v3]
    C --> E
    
    subgraph "Verification"
        E -->|Public API| H[GET /v1/certificates]
        H --> I[Deployment Gate]
        I -->|Verify Auth| J[Identity Registry]
        I -->|Verify Content| A
    end
```

### The Multi-Layer Forensic Defense
1.  **Trace Layer (Integrity)**: A SHA-256 hash of the `.jsonl` trace file ensures core execution has not been altered.
2.  **Evidence Layer (Provenance)**: The **Forensic Evidence Ledger** contains SHA-256 hashes of all sidecar artifacts (reports, plots), preventing report manipulation.
3.  **Manifest Layer (Authority)**: A signed JSON object (**Verification Certificate v3**) that binds these hashes to an identity via the **Identity Registry**.

---

## 2. Cryptographic Mechanics

### SHA-256 Content Hashing
The `TraceVerifier` performs streaming SHA-256 hashing of the trace file on-disk. This content-addressable signature ensures that if a single timestamp in the trace is modified, the hash changes, invalidating the entire protocol.

### Ed25519 Asymmetric Signing
We use the Ed25519 algorithm to sign the entire manifest.
- **Security**: Resistant to side-channel and collision attacks.
- **Efficiency**: signatures are only 64 bytes.
- **Detached Binding**: Signs the trace hash rather than the trace itself, eliminating the overhead of signing massive files.

---

## 4. Weighted Severity Model (WSM)

AgentV implements a **Weighted Severity Model (WSM)** for aggregate scoring, ensuring that risks are prioritized based on industrial impact.

| Dimension | weight | NIST AI-100-1 Alignment |
| :--- | :--- | :--- |
| **Safety** | 25% | Protection against physical or psychological harm. |
| **Security** | 20% | Resistance to adversarial attacks and exfiltration. |
| **Reliability** | 20% | Consistency and stability in mission-critical tasks. |
| **Fairness** | 15% | Mitigation of algorithmic and data-driven bias. |
| **Explainability** | 10% | Transparency of the agent's decision-making process. |
| **Privacy** | 5% | Compliance with data protection standards. |
| **Resilience** | 5% | Capacity to recover from unexpected state drift. |

### The "Safety Floor" Logic

:::important
**Deterministic Fail-Case**: If the score for **Safety** or **Security** falls below **0.5**, the aggregate trustworthiness index is automatically capped at **0.49 (Fail)**. This ensures that no amount of success in "Fairness" or "Efficiency" can mask a fundamental safety violation.
:::

---

## 5. Identity Registry, Key Management & Signing Interceptors

Core v1.4 replaces legacy file-based key loaders with the **Identity Registry** (`IdentityService`). This service abstracts private key resolution, supporting both local PEM storage and future cloud-native Vault/HSM integrations.

- **`LocalFileKeyLoader` (Default)**: Handles standard PEM files in the `.aes/keys` directory.
- **Enterprise Extensions**: Support for custom loaders that fetch keys directly from protected vaults.

### ⛓️ The Cryptographic Trace Signing Pipeline (v1.6.3)
To enable robust, customizable enterprise key routing and in-flight auditing, AgentV routes all trace signing and verification operations through a dynamic **Verifier Pipeline** inside `eval_runner/verifier.py`:

1.  **`TraceVerificationInterceptor`**: An abstract interface representing custom signing and verification interceptor classes.
2.  **`VerificationService` (`verification_service`)**: A thread-safe registry containing active trace interceptors. If a registered interceptor's `can_sign()` or `can_verify()` method returns `True`, operations are routed through that interceptor; otherwise, the pipeline falls back to standard core routines.
3.  **KMS / HSM Gating**: Allows enterprise plugins to delegate signing to an external hardware security module (HSM) or secure KMS vault without ever exposing raw private key bytes to the local filesystem or running memory.
4.  **WORM (Write Once, Read Many) Audit Trail Sealing**: Interceptors can write immutable execution proofs in-flight directly to `audit_chain.jsonl` as part of the sign sequence, locking results instantly against post-run tamper attempts.

---

## 6. Operational Gating (CI/CD)

The harness provides a production-grade utility for enforcing trust in automated pipelines.

### The `gate` Command
The `gate` utility is the final gatekeeper for production deployments. It exits with a non-zero code if:
1. The **Verification Certificate (VC)** signature is invalid.
2. The **Trace Hash** does not match the file on-disk.
3. Any item in the **Evidence Ledger** is missing or tampered with.

```bash
agentv gate --run-id <id> --verify-ledger
```

---

## 7. Security Guardrails

:::important
**Path Traversal Protection**: All file operations in the `verifier.py` engine are jail-checked. The protocol will refuse to sign or verify files outside of authorized evaluation directories.
:::

:::caution
**Key Isolation**: Private keys are stored in `.aes/keys` and are explicitly excluded from Git via `.gitignore`. Never commit private keys to the source repository.
:::
