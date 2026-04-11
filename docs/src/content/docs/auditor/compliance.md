---
title: Governance & Compliance
description: Forensic governance, NIST AI-100-1 alignment, and license obligations.
---

AgentV is designed for high-stakes industrial environments where traceability and regulatory compliance are non-negotiable.

## 1. Forensic Governance (v1.4.1)

AgentV mandates the **VC v3 forensic standard** for all production-grade evaluations.

- **Identity-based signing**: All traces are signed via the **Identity Registry** (ED25519) to ensure non-repudiation.
- **Forensic Evidence Ledger**: Every signed run includes a cryptographic ledger that hashes all associated sidecar artifacts (HTML reports, trajectory plots) to prevent side-channel tampering.
- **Environmental Provenance**: Every trace is mathematically bound to a **Provisioning Hash** of the registry state at the time of execution.
- **Hard Gating**: Deployment pipelines are enforced via the `agentv gate` command, which blocks promotion if cryptographic signatures or forensic hashes fail to match the sanctioned baseline.

## 2. NIST AI-100-1 Alignment

The framework satisfies industrial audit requirements defined by **NIST AI-100-1** (AI RMF principles) by providing:

1.  **WORM Logs**: Write-Once-Read-Many flight recorder logs (`run.jsonl`) that capture every atomic event.
2.  **Behavioral DNA**: High-granularity event tracing (PHASE, ACTION, STEP) for deep explainability.
3.  **Provisioning Provenance**: Mathematical proof of the environment state and simulator configuration.
4.  **VC v3 Verification**: Non-repudiable Verification Certificates with chained identity support.

## 3. License Obligations

### Core Framework License
AgentV is distributed under the **Apache License 2.0**.

### Third-Party Dependencies
The framework utilizes several permissive-licensed (MIT, BSD, Apache 2.0) libraries.

| Package | License |
| :--- | :--- |
| **aiohttp**, **requests**, **datasets** | Apache 2.0 |
| **Flask**, **numpy** | BSD-3-Clause |
| **jsonschema**, **PyYAML**, **PyJWT** | MIT |
| **cryptography** | Apache 2.0 / BSD |
| **google-genai** | Apache 2.0 |

:::warning
While the `datasets` library is Apache 2.0, individual datasets (e.g., loaded via `gaia://`) may have their own licenses. **Always verify the specific dataset terms before commercial use.**
:::

## 4. Security & Safety Obligations

- **Safe YAML**: The framework exclusively uses `yaml.safe_load()` to mitigate arbitrary code execution risks.
- **Credential Stripping**: Automated logic strips sensitive keys (API keys, tokens) from metadata before trace signing.
- **WORM Audit Trail**: Append-only execution logging prevents modification of historical performance data.
