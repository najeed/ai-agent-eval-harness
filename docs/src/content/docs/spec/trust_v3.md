---
title: "Forensic Trust Protocol v3.0.0"
description: "Authoritative specification for cryptographic evaluation integrity"
---

# 1. Overview
The Forensic Trust Protocol v3.0.0 (Forensic Standard) extends the base Trust Protocol to provide immutable evidence for every sidecar artifact generated during an evaluation attempt.

# 2. Schema
The VC v3 manifest follows the [Industrial Forensic JSON Schema](/spec/vc/vc.schema.json).

## Key Extensions
- **`evidence_ledger`**: A map of SHA3-256 hashes for all physical artifacts (e.g. `terminal.log`, `database.sqlite`).
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

# 3. Industrial Gating & Identity (AES v1.4)
To ensure audit-grade forensic stability, the protocol enforces strict identity resolution rules:

- **Zero-Inference Policy**: The `run_id` MUST be explicitly provided during certification. Speculative inference from parent directory names is prohibited unless reconciled against an vault.
- **Provider Affinity**: Verification is permitted only against the execution owner's scoped provider record: its exact committed trace bytes and its manifest. Filesystem paths and master logs are not verification inputs.
- **Provider Portability**: Evidence references MUST use provider-neutral identities or URIs; a LocalFile provider may map those to paths internally without exposing paths to Core.

# 4. Cryptographic Requirements & Evidence Graph
- **Algorithm**: Ed25519 (Asymmetric) / SHA3-256 (Hashing) / ML-DSA-65 (NIST FIPS 204 PQC).
- **RFC 8785 JCS Canonicalization**: All cryptographic hashes and signatures MUST be computed over canonical JSON serialized in strict accordance with the RFC 8785 JSON Canonicalization Scheme (JCS) (`agentv_runtime.canonical`). Keys are sorted by UTF-16 code units and floating point numbers format per ECMAScript 7.1.12.1.
- **Whole-Envelope Detached Trace Seal**: The trace seal detached signature covers the complete canonical envelope (`run_id`, `trace_digest`, `event_count`, `sealed_at`, `signer_identity`, `key_id`, `algorithm`, `metadata`) prior to attaching the detached signature.
- **External Trust Root Mandate**: Verification strictly requires an external trust root or key registry (`public_key_pem`, `trust_roots`, or `trusted_keys`). Unanchored, embedded, or auto-generated ephemeral keys yield `UNVERIFIED` and are prohibited from asserting authenticity.
- **Evidence Graph Root Binding**: The certificate must bind an `evidence_root_hash` computed over the canonical assertion node linkages (`compute_evidence_graph_root`).
- **Direct Trace Provenance**: Verification strictly mandates `is_complete_provenance = True`. If any evaluated assertion relies on a fallback or terminal carrier sequence instead of direct execution event linkage, verification fails closed (`DirectProvenanceViolation`).
- **Scenario Canonical Hash Binding**: The certificate is bound to `scenario_hash` computed from the canonical scenario definition (`compute_scenario_hash`). Tampered scenario definitions fail verification immediately.

# 5. Authoritative Verdict Precedence & Fail-Closed Persistence
- **No Caller Overrides**: Compliance status and score are derived authoritatively from verifiable execution events. Caller-supplied status overrides are strictly rejected.
- **Precedence Hierarchy**: Any terminal failure status (`failed`, `timeout`, `policy_breach`, `error`) takes absolute precedence over optimistic heuristic counters (`passed=True`, `success_rate`).
- **Intrinsically Fail-Closed Persistence**: In certification or attestation mode, any event write failure (disk full, I/O disruption) immediately aborts the run into `CERTIFICATION_FAILED`, tracks the failed run, and strictly refuses seal, certificate, or package generation.

## 5.1 Storage Classification & Immutable WORM Mandate (`REQUIRE_IMMUTABLE_WORM`)
To eliminate ambiguous compliance claims, AgentV establishes a strict classification boundary between logical tamper-evidence and physical immutable storage:

- **`TAMPER_EVIDENT_LOGICAL_SEAL`**:
  The default Open Core storage backend (`eval_runner.reference.LocalFileArtifactStore`) provides high-integrity logical seals. It captures retention metadata (`retention_days`, `retention_until`, `legal_hold`), writes `.sealed` sentinels, and rejects programmatic mutation. However, because host operating system filesystems can be altered by privileged local administrators, it is classified strictly as a logical seal, not hardware WORM.
- **`PHYSICAL_IMMUTABLE_WORM`**:
  Enterprise storage backends (e.g. AWS S3 Object Lock in COMPLIANCE mode, Azure Immutable Blob Storage) that enforce hardware-level write-once immutability.
- **Fail-Closed Certification Gate**:
  When immutable retention is claimed or required by configuration (`REQUIRE_IMMUTABLE_WORM=true`), `CertificationService` and `TraceVerifier` inspect the active `ArtifactStore`. If the active store is classified as `TAMPER_EVIDENT_LOGICAL_SEAL`, certification is unconditionally blocked and fails closed with:
  ```text
  CertificationVerificationError: Storage tier provides TAMPER_EVIDENT_LOGICAL_SEAL, but immutable physical WORM is required by policy.
  ```

# 6. Use Cases
- **Regulatory Audits**: Providing high-fidelity proof for healthcare or finance agents under NIST AI 100-1, SOC 2 Type II, and EU AI Act.
- **Zero-Trust CI/CD**: Using the `gate` command to verify integrity and evidence graph completion before deployment.
