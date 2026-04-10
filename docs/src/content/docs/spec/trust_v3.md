---
title: "Forensic Trust Protocol v3.0.0"
description: "Authoritative specification for cryptographic evaluation integrity"
---

# 1. Overview
The Forensic Trust Protocol v3.0.0 (Forensic Standard) extends the base Trust Protocol to provide immutable evidence for every sidecar artifact generated during an evaluation attempt.

# 2. Schema
The VC v3 manifest follows the [Industrial Forensic JSON Schema](file:///c:/Users/najee/OneDrive/Documents/Projects/ai-agent-eval-harness/spec/vc/vc.schema.json).

## Key Extensions
- **`evidence_ledger`**: A map of SHA-256 hashes for all physical artifacts (e.g. `terminal.log`, `database.sqlite`).
- **`provenance_chain`**: A multi-party signature history allowing Agent, Evaluator, and Auditor to sign the same result.
- **`compliance`**: Mandatory root object for regulatory scoring (e.g. NIST, SOC2).

## Artifact Filtering & Relevance
To ensure forensic performance and prevent bloat, artifacts are gathered via the **Forensic Relevance Engine**.

### Three-Tier Collection Model
1. **Tier 1 (Core)**: All files in the `forensics/` folder are collected unconditionally.
2. **Tier 2 (Administrative)**: Files matching `FORENSIC_MANDATORY_PATTERNS` bypass all size and extension filters.
3. **Tier 3 (Functional)**: General artifacts (e.g., `.log`, `.json`, `.sql`) are collected if they are below the `FORENSIC_MAX_ARTIFACT_SIZE` (Default: 5MB).
    - **Whitelisted Extensions**: `.jsonl`, `.log`, `.json`, `.png`, `.jpg`, `.pdf`, `.csv`, `.db`, `.sqlite`, `.txt`, `.parquet`, `.yaml`, `.yml`, `.sql`, `.patch`, `.diff`, `.zip`, `.tar.gz`, `.tgz`, `.html`, `.svg`
    - **Supported Aliases**: `.jpeg` -> `.jpg`, `.stdout`/`.stderr`/`.err` -> `.log`, `.sqlite3`/`.db3` -> `.db`.

# 3. Cryptographic Requirements
- **Algorithm**: ED25519 (Asymmetric) / SHA-256 (Hashing).
- **Deterministic Signing**: Signatures MUST be computed by excluding the `provenance_chain` from the payload to allow for multi-party appending without invalidating existing signatures.

# 4. Use Cases
- **Regulatory Audits**: Providing high-fidelity proof for healthcare or finance agents.
- **Zero-Trust CI/CD**: Using the `gate` command to verify integrity before deployment.
