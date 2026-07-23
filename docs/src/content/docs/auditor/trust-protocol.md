---
title: Trust Protocol Standard
description: The industrial standard for non-repudiable evaluation traces and forensic integrity.
---

The Trust Protocol (v1.6.0) provides **immutable proof of run integrity** for the AgentV Harness. It employs a "Detached Signature" architecture that separates bulky execution data from metadata certificates.

## 1. Forensic Architecture

AgentV uses a tiered approach to ensure that evaluation results are authentic and tamper-proof.

```mermaid
graph TD
    A[Trace File .jsonl] -->|SHA3-256| B[Content Hash]
    B --> C[Manifest v3 Metadata]
    S[Artifact Sidecars] -->|SHA3-256| L[Evidence Ledger]
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
1.  **Trace Layer (Integrity)**: A SHA3-256 hash of the `.jsonl` trace file ensures core execution has not been altered.
2.  **Evidence Layer (Provenance)**: The **Forensic Evidence Ledger** contains SHA3-256 hashes of all sidecar artifacts (reports, plots), preventing report manipulation.
3.  **Manifest Layer (Authority)**: A signed JSON object (**Verification Certificate v3**) that binds these hashes to an identity via the **Identity Registry**.

---

## 2. Cryptographic Mechanics

### SHA3-256 Content Hashing
The `TraceVerifier` performs streaming SHA3-256 hashing of the trace file on-disk. This content-addressable signature ensures that if a single timestamp in the trace is modified, the hash changes, invalidating the entire protocol.

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

## 5a. Verification Certificate (VC) v3 JSON Schema

The Verification Certificate (`run_manifest.json`) is the core non-repudiability artifact. Its schema conforms to the following structured definition:

```json
{
  "run_id": "test_run_123",
  "trace_file": "run.jsonl",
  "trace_hash": "4a7f98e8a93a...",
  "vc_version": "3.0.0",
  "governance_ttl": 90,
  "metadata": {
    "git_hash": "a1b2c3d4...",
    "seal_hash": "e5f6a7b8...",
    "provisioning_hash": "d9e8f7...",
    "timestamp": "2026-07-01T12:00:00Z"
  },
  "evidence_ledger": {
    "reports/latest_summary.html": "9a8b7c6d...",
    "plots/trajectory.png": "f1e2d3c4..."
  },
  "provenance_chain": [
    {
      "identity": "system_id",
      "signature": "3c8a9f2b1d0...",
      "timestamp": 1712904000.456,
      "algorithm": "Ed25519"
    }
  ]
}
```

*   **`trace_hash`**: Streaming SHA3-256 hash of the `run.jsonl` trace file.
*   **`evidence_ledger`**: Mapping of sidecar artifact paths to their SHA3-256 integrity hashes.
*   **`metadata.seal_hash`**: The hash computed over the trace history immediately prior to appending the certification event.
*   **`provenance_chain`**: A list of signatures binding the manifest digest to classical or post-quantum identity keys.

---

## 5b. Seal Hash Protocol & OS-Independent Trace Verification

### The Seal Hash Anchor
To mathematically bind the certification to the specific execution sequence:
1. Prior to appending the `verification_certificate_issued` event, the engine reads the current trace history.
2. It computes a SHA3-256 hash of this history (`seal_hash`).
3. This `seal_hash` is written inside the Verification Certificate metadata.
4. If any historical event in the trace is modified after certification, the recalculated `seal_hash` will mismatch, invalidating the certificate.

### Binary Trace Integrity
To prevent cross-platform signature failures caused by line-ending conversion (e.g. Windows `\r\n` vs Linux `\n`), AgentV enforces **binary mode trace writes**:
*   All trace events are encoded as UTF-8 bytes and appended directly to the physical file without OS-level newline translations.
*   SHA3-256 verification hashes the raw byte stream on disk, ensuring identical hash checksums on Windows, Linux, and macOS.

---

## 5c. Custom Signing Interceptor Development

Developers can customize key routing and audit logging by registering a subclass of `TraceVerificationInterceptor`:

```python
from eval_runner.verifier import TraceVerificationInterceptor, verification_service

class MyEnterpriseKMSInterceptor(TraceVerificationInterceptor):
    def can_sign(self, identity_id: str) -> bool:
        return identity_id.startswith("kms-")

    def sign(self, data: bytes, identity_id: str) -> dict:
        # Resolve key and sign remotely via KMS API
        signature = call_kms_sign_api(data, identity_id)
        return {
            "identity": identity_id,
            "signature": signature.hex(),
            "algorithm": "kms-hsm-hybrid"
        }

    def can_verify(self, identity_id: str) -> bool:
        return identity_id.startswith("kms-")

    def verify(self, data: bytes, signature_hex: str, identity_id: str) -> bool:
        # Call KMS public key verification endpoint
        return call_kms_verify_api(data, signature_hex, identity_id)

# Register the interceptor in the global Verifier pipeline
verification_service.register_interceptor(MyEnterpriseKMSInterceptor())
```

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
