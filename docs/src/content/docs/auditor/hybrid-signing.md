---
title: Hybrid PQC Signing
description: Industrial-grade quantum-resistant non-repudiation and fail-closed signing for AI agent evaluations.
---

import { Steps, Aside, Tabs, TabItem } from '@astrojs/starlight/components';

# Hybrid Post-Quantum Cryptographic (PQC) Signing

AgentV OS Runtime `v2.0.0` provides first-class support for **Hybrid Post-Quantum Cryptographic (PQC) Signing** and **Fail-Closed Cryptographic Enforcement**. This protocol protects industrial forensic traces against quantum computing threats while maintaining strict data privacy through the **Zero-Exposure Signing (ZES)** pattern.

---

## 🏗️ Architecture

The hybrid protocol combines classical elliptic curve cryptography with modern lattice-based algorithms:

1.  **Classical Layer**: Ed25519 (SHA-512 + Curve25519) via `LocalEd25519SigningBackend` for high-performance, universally compatible signing.
2.  **Post-Quantum Layer**: ML-DSA-65 (Module-Lattice-based Digital Signature Algorithm) via `PQCSigningBackend`, aligned with NIST's **FIPS 204** standard.
3.  **Hybrid Binding**: Both signatures are mathematically bound to the same **Verification Certificate (VC) v3.0.0** and stored in the `provenance_chain`.
4.  **Pluggable `SigningBackend` Interface**: Custom KMS, HSM, or PQC backends can be injected directly via `agentv_runtime.interfaces.SigningBackend`.

---

## 🔒 Fail-Closed Cryptographic Enforcement

AgentV enforces strict cryptographic safety gates during evaluation:

> [!IMPORTANT]
> **Mandatory Signing Rules**: When `EVAL_REQUIRE_SIGNING=true` or `AUDIT_LEVEL >= 2` and no valid signing key or `SigningBackend` is provided, the runtime immediately raises a `RuntimeError` (`"CryptographicSigningError: Signing is mandatory..."`). Silent unauthenticated evaluations are strictly rejected.

---

## 🧬 Zero-Exposure Signing (ZES) Protocol

To maintain the privacy of industrial evaluation data, AgentV implements the **Zero-Exposure Signing (ZES)** pattern. Raw traces, trajectories, and sensitive logs never leave the project's security jail.

### The ZES Flow

<Steps>

1.  **Generate Manifest (VC v3.0.0)**
    The harness assembles `run_manifest.json` containing the trace hash and forensic evidence ledger.

2.  **Compute SHAKE-256 Digest**
    The manifest is hashed locally using **SHAKE-256** to create a fixed-length (32-byte) cryptographic digest.

3.  **Zero-Exposure Transmission**
    Only the resulting 32-byte digest is transmitted to the PQC provider along with the identity configuration. **Raw trace data never leaves your environment.**

4.  **Remote or Local Lattice Signing**
    The provider signs the digest using the **ML-DSA-65** algorithm and returns the signature hex.

5.  **Seal Certificate**
    The signature is appended to `provenance_chain` as an `ML-DSA-65` node and the Verification Certificate is sealed.
</Steps>

<Aside type="tip">
ZES ensures that even if the PQC provider is compromised, your proprietary agent trajectories remain private as they were never shared.
</Aside>

---

## 💻 Programmatic PQC Signing Backend

Extenders and test suites can use `PQCSigningBackend` directly:

```python
from agentv_runtime.reference import PQCSigningBackend

pqc_backend = PQCSigningBackend()
sig_hex = pqc_backend.sign_payload(b'{"eval":"success"}', key_identifier="sys_pqc")
is_valid = pqc_backend.verify_signature(
    b'{"eval":"success"}', sig_hex, public_key_identifier="sys_pqc"
)
```

---

## ⚙️ Configuration (Environment Variables)

<Tabs>
  <TabItem label="Core Setup" icon="setting">

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PQC_ENABLED` | `false` | Set to `true` to activate the hybrid signing pipeline. |
| `PQC_PROVIDER` | `cyclecore` | The cryptographic provider (e.g., `cyclecore`). |
| `PQC_STRICT_MODE` | `false` | If `true`, fails evaluation if PQC signing fails. |
| `EVAL_REQUIRE_SIGNING` | `false` | If `true`, fails closed (`RuntimeError`) if signing key is absent. |
| `AUDIT_LEVEL` | `1` | Level >= 2 enforces mandatory signing and audit ledgers. |
  </TabItem>
  <TabItem label="Provider Keys" icon="key">

| Variable | Default | Description |
| :--- | :--- | :--- |
| `CYCLECORE_API_KEY` | *(None)* | Your ZES API key (Required for remote signing). |
| `PQC_IDENTITY_ID` | `default` | The identity name for the PQC signature. |
  </TabItem>
</Tabs>

---

## ⚖️ NIST Alignment

The Hybrid PQC implementation is explicitly aligned with **NIST AI-100-1** and **NIST FIPS 204**, providing a non-repudiable bridge between raw evaluation data and regulatory-grade compliance reports.
