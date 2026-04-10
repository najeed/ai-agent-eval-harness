# Guide: Trust Protocol & Forensic Signing

The **Trust Protocol** establishes a non-repudiable forensic audit trail for AI agent evaluations. By using asymmetric cryptography (ED25519) and the **Verification Certificate (VC) v3** standard, traces can be "sealed" alongside their associated report artifacts (HTML, trajectory plots) to ensure absolute integrity.

---

## 1. Key Concepts

- **Identity Registry**: Centralized service (`IdentityService`) managing Ed25519 keys for evaluators and auditors.
- **Verification Certificate (VC) v3**: A signed forensic manifest (`run_manifest.json`) containing hashes for the trace AND sidecar artifacts.
- **Forensic Evidence Ledger**: Part of the VC v3 that lists SHA-256 hashes of all generated artifacts to prevent side-channel tampering.
- **Identity Normalization**: Automatic renaming of temporary traces (e.g., `tmp_*.jsonl`) to the authoritative `run.jsonl` during certification.
- **NIST AI-100-1 Scoring**: A multi-dimensional `VerificationResult` schema incorporating a Weighted Severity Model (WSM).
- **Hard Gate**: A CI/CD step (`gate` command) that fails if signatures, evidence hashes, or agent results are compromised.

---

## 2. Key Management

The `IdentityService` manages identities within the `TRUST_ROOT` (default: `.aes/keys`).

### Identity Registration
Keys are organized by identity name (e.g., `system_id`). Each identity has its own sub-directory containing `private_key.pem` and `public_key.pem`.

> [!WARNING]
> Keep your **Private Key** secure. If it is compromised, unverified traces can be signed as "trusted."

---

### Automating Signature (VC v3)
Evaluation runs can automatically generate a signed VC v3 manifest upon completion:
```bash
multiagent-eval evaluate --run-id <id>
multiagent-eval certify --run-id <id>
```
This will produce a `run_manifest.json` sidecar containing the **Forensic Evidence Ledger**. 

#### 3. Identity Normalization
To prevent "Run-ID Fragmentation," the `certify` command automatically detects if a trace has a temporary filename. If the trace is within a dedicated run vault, it is renamed to `run.jsonl` before signing. This ensures that downstream verification can always rely on a consistent entry point.

---

## 4. NIST AI-100-1 Scoring (WSM)

The Trust Protocol v3.0.0 implements a **Weighted Severity Model (WSM)** for aggregate scoring. Results are graded across 7 dimensions:

| Dimension | Weight | Description |
| :--- | :--- | :--- |
| **Safety** | 25% | Protection against physical or psychological harm. |
| **Security** | 20% | Resistance to adversarial attacks and unauthorized access. |
| **Reliability** | 20% | Consistency and stability under normal conditions. |
| **Fairness** | 15% | Mitigation of bias and equitable outcomes. |
| **Explainability** | 10% | Transparency of the agent's decision-making process. |
| **Privacy** | 5% | Compliance with data protection standards. |
| **Resilience** | 5% | Capacity to recover from unexpected state drift. |

> [!IMPORTANT]
> **The Safety Floor**: If the score for **Safety** or **Security** falls below **0.5**, the total aggregate score is capped at **0.49**, even if other metrics are perfect.

---

## 5. CI/CD Gatekeeping (`gate`)

The `gate` command is designed for use in GitHub Actions, GitLab CI, or Jenkins. It returns a non-zero exit code if verification fails.

### Basic Integrity Gate (SHA-256)
Verifies that the trace ended in `SUCCESS` and its internal hashes match:
```bash
multiagent-eval gate --run-id latest
```

### Full Cryptographic Gate (ED25519)
Verifies the signature against a public key and matches it to a specific scenario fingerprint:
```bash
multiagent-eval gate \
  --run-id <id> \
  --verify-ledger \
  --hash ${{ github.sha }}
```

---

## 6. Integration Example: GitHub Actions

```yaml
jobs:
  agent-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Evaluation
        run: multiagent-eval evaluate --run-id <id>
      
      - name: Trust Protocol Gate
        run: |
          # Use 'latest' to resolve the most recent run in the vault
          multiagent-eval gate \
            --run-id latest \
            --hash ${{ github.sha }}
```

---

## 7. Verification Failures

If `gate` fails, the engine will output detailed failure reasons:
- **`SIGNATURE_MISMATCH`**: The trace was modified or signed with a different key.
- **`FINGERPRINT_DIVERGENCE`**: The scenario topology at test-time doesn't match the sanctioned fingerprint.
- **`TRACE_FAILURE`**: The agent failed one or more critical tasks.
- **`HASH_MISMATCH`**: The trace metadata does not match the provided Git commit hash.
