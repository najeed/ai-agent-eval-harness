---
title: Hybrid PQC Signing
description: Industrial-grade quantum-resistant non-repudiation for AI agent evaluations.
---

import { Steps, Aside, Tabs, TabItem } from '@astrojs/starlight/components';

# Hybrid Post-Quantum Cryptographic (PQC) Signing

AgentV v1.6.2 introduces support for **Hybrid Post-Quantum Cryptographic (PQC) Signing**. This protocol is designed to protect industrial forensic traces against emerging quantum computing threats while maintaining strict data privacy through the **Zero-Exposure Signing (ZES)** pattern.

This guide is intended for **Auditors**, **Integrators**, and **Evaluators** who need to ensure the long-term non-repudiability of agentic evaluation results.

---

## 🏗️ Architecture

The hybrid protocol combines classical elliptic curve cryptography with modern lattice-based algorithms, ensuring that the system remains secure even if one of the layers is compromised.

1.  **Classical Layer**: Ed25519 (SHA-512 + Curve25519) - Used for high-performance, universally compatible signing.
2.  **Post-Quantum Layer**: ML-DSA-65 (Module-Lattice-based Digital Signature Algorithm) - Aligned with NIST's FIPS 204 standard for quantum resistance.
3.  **Hybrid Binding**: Both signatures are mathematically bound to the same **Verification Certificate (VC) v3.0.0** and stored in the `provenance_chain`.

---

## 🧬 Zero-Exposure Signing (ZES) Protocol

To maintain the privacy of industrial evaluation data, AgentV implements the **Zero-Exposure Signing (ZES)** pattern. This ensures that raw traces, trajectories, and sensitive logs never leave the project's security jail.

### The ZES Flow

<Steps>

1.  **Generate Manifest (VC v3)**
    The harness assembles the `run_manifest.json` containing the trace hash and forensic evidence ledger.

2.  **Compute SHAKE-256 Digest**
    The manifest is hashed locally using **SHAKE-256**. This creates a fixed-length (32-byte) cryptographic condensation of the data.

3.  **Secure Transmission**
    Only the resulting 32-byte digest is transmitted to the PQC provider (CycleCore) along with your API Key. **The raw trace data never leaves your environment.**

4.  **Remote Signing**
    The provider signs the digest using the **ML-DSA-65** algorithm and returns the signature hex.

5.  **Seal Certificate**
    The signature is appended to the `provenance_chain` and the Verification Certificate is sealed for final audit.
</Steps>

<Aside type="tip">
ZES ensures that even if the PQC provider is compromised, your proprietary agent trajectories remain private as they were never shared.
</Aside>

---

## ⚙️ Configuration (Environment Variables)

Enable and configure Hybrid PQC using the following parameters. You can set these in your `.env` file.

<Tabs>
  <TabItem label="Core Setup" icon="setting">

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PQC_ENABLED` | `false` | Set to `true` to activate the hybrid signing pipeline. |
| `PQC_PROVIDER` | `cyclecore` | The cryptographic provider (e.g., `cyclecore`). |
| `PQC_STRICT_MODE` | `false` | If `true`, fails evaluation if PQC signing fails. |
  </TabItem>
  <TabItem label="CycleCore Keys" icon="key">

| Variable | Default | Description |
| :--- | :--- | :--- |
| `CYCLECORE_API_KEY` | *(None)* | Your ZES API key (Required for remote signing). |
| `CYCLECORE_IDENTITY_ID`| `default` | The identity name for the PQC signature. |
  </TabItem>
</Tabs>

---

## 🛠️ Troubleshooting

### Common CycleCore API Errors

| Error Symptom | Potential Cause | Resolution |
| :--- | :--- | :--- |
| `Authentication Failure` | Invalid or expired `CYCLECORE_API_KEY`. | Check your environment variables and CycleCore dashboard. |
| `Rate Limit Exceeded` | Too many concurrent signing requests. | Implement `ADAPTER_RETRY_DELAY` or contact support for higher limits. |
| `Connection Timeout` | Network/Firewall blocking egress to the PQC provider. | Ensure your host can reach the CycleCore API endpoints. |
| `ImportError: cyclecore-pq` | The `cyclecore-pq` package is missing. | Run `pip install cyclecore-pq` or check your `pyproject.toml`. |

### Verification Failures

*   **Signature Mismatch**: Ensure the `PQC_IDENTITY_ID` used during signing matches the one configured during verification.
*   **Hash Inconsistency**: If the local `SHAKE-256` digest differs from the one recorded in the manifest, verification will fail automatically to prevent tampering.

---

## ⚖️ NIST Alignment

The Hybrid PQC implementation is explicitly aligned with **NIST AI-100-1** and **NIST FIPS 204**, providing a non-repudiable bridge between raw evaluation data and regulatory-grade compliance reports.
