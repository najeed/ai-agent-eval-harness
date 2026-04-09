# Guide: Trust Protocol & Forensic Signing

The **Trust Protocol** establishes a non-repudiable forensic audit trail for AI agent evaluations. By using asymmetric cryptography (ED25519) and the **Verification Certificate (VC) v3** standard, traces can be "sealed" alongside their associated report artifacts (HTML, trajectory plots) to ensure absolute integrity.

---

## 1. Key Concepts

- **Identity Registry**: Centralized service (`IdentityService`) managing Ed25519 keys for evaluators and auditors.
- **Verification Certificate (VC) v3**: A signed forensic manifest (`manifest.json`) containing hashes for the trace AND sidecar artifacts.
- **Forensic Evidence Ledger**: Part of the VC v3 that lists SHA-256 hashes of all generated artifacts to prevent side-channel tampering.
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
multiagent-eval evaluate --path scenarios/finance --sign
```
This will produce a `manifest.json` sidecar containing the **Forensic Evidence Ledger**.

---

## 4. CI/CD Gatekeeping (`gate`)

The `gate` command is designed for use in GitHub Actions, GitLab CI, or Jenkins. It returns a non-zero exit code if verification fails.

### Basic Integrity Gate (SHA-256)
Verifies that the trace ended in `SUCCESS` and its internal hashes match:
```bash
multiagent-eval gate --path reports/run.jsonl
```

### Full Cryptographic Gate (ED25519)
Verifies the signature against a public key and matches it to a specific scenario fingerprint:
```bash
multiagent-eval gate \
  --path reports/run.jsonl \
  --vc scenarios/finance/fingerprint.json \
  --public-key keys/prod_public.pem \
  --hash ${{ github.sha }}
```

---

## 5. Integration Example: GitHub Actions

```yaml
jobs:
  agent-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Evaluation
        run: multiagent-eval evaluate --path scenarios/production/
      
      - name: Trust Protocol Gate
        run: |
          multiagent-eval gate \
            --path runs/run.jsonl \
            --hash ${{ github.sha }}
```

---

## 6. Verification Failures

If `gate` fails, the engine will output detailed failure reasons:
- **`SIGNATURE_MISMATCH`**: The trace was modified or signed with a different key.
- **`FINGERPRINT_DIVERGENCE`**: The scenario topology at test-time doesn't match the sanctioned fingerprint.
- **`TRACE_FAILURE`**: The agent failed one or more critical tasks.
- **`HASH_MISMATCH`**: The trace metadata does not match the provided Git commit hash.
