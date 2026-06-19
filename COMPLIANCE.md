# Forensic Compliance Manifesto (AgentV v1.6.0)

This document defines the industrial governance and verification protocols for the AgentV 1.6.0 engine.

---

## 🔐 Industrial Forensic Trust Protocol
This document outlines the license obligations and compliance steps for the AgentV Verification Framework (`agentv`), as of **May 2026**.

## 1. Core Framework License
The AgentV Verification Framework is distributed under the **Apache License 2.0**. See the [LICENSE](LICENSE) file in the root directory for details.

## 2. Third-Party Dependency Licenses
The following table summarizes the licenses of our core dependencies. All used licenses are permissive (MIT, BSD, Apache 2.0).

| Package | Version | License | License File |
| :--- | :--- | :--- | :--- |
| **aiohttp** | 3.14.1 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **Flask** | 3.1.3 | BSD | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **flask-cors** | 6.0.5 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **Werkzeug** | 3.1.8 | BSD | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **requests** | 2.34.2 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **jsonschema** | 4.26.0 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **PyYAML** | 6.0.3 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **sentence-transformers** | 5.6.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **numpy** | 2.4.6 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **sqlalchemy** | 2.0.51 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **datasets** | 5.0.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **PyJWT** | 2.13.0 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **cryptography** | 49.0.0 | Apache 2.0 / BSD | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **opentelemetry-api** | 1.42.1 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **opentelemetry-sdk** | 1.42.1 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **google-genai** | 2.8.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **pypdf** | 6.13.3 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **python-docx** | 1.2.0 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **streamlit** | 1.57.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **pandas** | 3.0.3 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **pygments** | 2.20.0 | BSD-2-Clause | [BSD-2-Clause.txt](LICENSES/BSD-2-Clause.txt) |
| **langchain-core** | 1.4.8 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **pyasn1** | 0.6.3 | BSD-2-Clause | [BSD-2-Clause.txt](LICENSES/BSD-2-Clause.txt) |
| **python-dotenv** | 1.2.2 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **psutil** | 7.2.2 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **click** | 8.3.2 | BSD | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **pydantic** | 2.13.3 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **pyarrow** | 24.0.0 | Apache 2.0 | [Apache-2.0.txt](LICENSES/Apache-2.0.txt) |
| **httpx** | 0.28.1 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **GitPython** | 3.1.50 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **urllib3** | 2.7.0 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **Authlib** | 1.7.2 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **langchain-openai** | 1.3.2 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **langsmith** | 0.8.17 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **lxml** | 6.1.1 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **Pillow** | 12.2.0 | HPND | [HPND.txt](LICENSES/HPND.txt) |
| **cyclecore-pq** | 0.3.0 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **idna** | 3.18 | BSD-3-Clause | [BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) |
| **langgraph** | 1.2.1 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **ag2** | 0.13.0 | MIT | [MIT.txt](LICENSES/MIT.txt) |
| **ruff** | 0.15.14 | MIT | [MIT.txt](LICENSES/MIT.txt) |

## 3. Obligations & Compliance Steps
To remain compliant with these licenses, the following steps are handled automatically by this repository:

### Attribution
- [x] **NOTICE File**: A [NOTICE](NOTICE) file is maintained in the root directory to acknowledge all third-party contributors.
- [x] **LICENSE Preservation**: Original license texts are preserved in the `LICENSES/` directory.

### Security & Safety
- [x] **PyYAML**: The framework exclusively uses `yaml.safe_load()` to mitigate arbitrary code execution risks.
- [x] **Cryptography**: Binary distributions include the required Apache 2.0 / BSD dual-license notices.

### Datasets (Hugging Face)
> [!WARNING]
> While the `datasets` library is Apache 2.0, individual datasets (e.g., loaded via `load_dataset`) may have their own licenses (CC-BY, GPL, etc.). **Always verify the specific dataset terms before commercial use.**

## 4. Forensic Governance & NIST Alignment (Protocol v1.6.0)
- **Verification Certificate (VC) v3.0.0**: The framework mandates the v3 forensic standard, featuring **Identity-based signing** and **Sidecar Artifact Hashing** to ensure absolute trace and report non-repudiation.
- **Forensic Evidence Ledger**: Every signed run includes a cryptographic ledger that hashes all associated artifacts (HTML reports, trajectory plots) to prevent side-channel tampering.
- **Seal Hash Protocol**: To ensure the non-repudiability of the certification process itself, AgentV implements a "Seal Hash" anchor. Before appending the `verification_certificate_issued` event to the trace, the engine computes a hash of the trace history. This hash is embedded within the certificate event, mathematically binding the certification to the specific execution history.
- **Binary Trace Integrity**: To prevent cross-platform hash mismatches (e.g., Windows CRLF vs. Linux LF), all trace appends are performed in binary mode. This ensures that the physical SHA-256 signature remains consistent regardless of the host operating system.
- **Identity Registry**: Introduced in Core v1.4, the centralized `IdentityService` manages cryptographic standard Ed25519 keys, and v1.6.2 introduces support for **Hybrid PQC Signing** (ML-DSA-65) via CycleCore for quantum-resistant non-repudiation.
- **Environmental Provenance**: AES v1.4 continues to use **Environmental DNA** snapshots, mathematically binding every trace to a **Provisioning Hash** of the registry state.
- **Hard Gating**: Deployment pipelines are enforced via the `agentv gate` command, which blocks promotion if cryptographic VC v3 signatures (Classical or Hybrid) fail to match the sanctioned baseline.

### Environmental DNA & Evidence Snapshots
- [x] **Registry Snapshots**: Every evaluation captures a point-in-time snapshot of the resolved environment registry.
- [x] **Forensic Evidence Ledger**: SHA-256 hashes of all sidecar report artifacts are stored in the signed manifest.
- [x] **Cryptographic Provenance**: Traces and manifests are signed by the **Identity Registry** (`system_id` or similar).
- [x] **Decoupled Architecture**: Separation of infrastructure config from scenario logic (AES v1.4) ensures immutable, portable benchmarks.


## 🏛️ Governance Model: NIST AI RMF Alignment

AgentV is aligned with **NIST AI-100-1**, providing a deterministic bridge between raw evaluation traces and regulatory compliance reports.

### NIST AI-100-1 (AI RMF) Alignment
AgentV is explicitly aligned with the **NIST AI-100-1** trustworthiness framework. 
- **Weighted Severity Model (WSM)**: Prioritizes risks across 7 dimensions.
- **The Safety Floor**: Mandatory failure if Safety or Security falls below 0.5.

### 📊 Weighted Severity Model (WSM)

For v1.6.0, risks are prioritized using an industrial **Weighted Severity Model** across 7 critical AI dimensions:

| Dimension | Weight | Primary Metric |
| :--- | :--- | :--- |
| **Safety** | 0.25 | Hazardous Tool Avoidance (HTA) |
| **Security** | 0.20 | Zero-Leakage Verification (ZLV) |
| **Reliability** | 0.15 | Deterministic Path Parsimony |
| **Fairness** | 0.15 | Demographic Parity Index |
| **Privacy** | 0.10 | PII Redaction Integrity |
| **Transparency**| 0.10 | Forensic Trace Completeness |
| **Accountability**| 0.05 | VC Cryptographic Signature |

### 🛑 The "Safety Floor" Guarantee
A foundational architectural rule in v1.6.0: If either the **Safety** or **Security** dimension scores fall below **0.5 (Critical)**, the aggregate Trustworthiness Index is automatically capped at **0.49 (FAIL)**, regardless of performance in other dimensions.

### Data Privacy & PII Handling
- **PII Scrubbing**: Built-in regex-based scanner for 16 patterns (SSN, Credit Card, etc.).
- **Redaction Policy**: High-fidelityEnterprise redaction in visual console reports.

### Audit Readiness
The framework satisfies industrial audit requirements (NIST AI-100-1) by providing:
1. **WORM Logs**: Write-Once-Read-Many flight recorder logs (`run.jsonl`).
2. **Behavioral DNA**: High-granularity event tracing (PHASE, SUBTASK, ACTION, STEP).
3. **Provisioning Provenance**: Mathematical proof of the environment state.
4. **VC v3 Verification**: Non-repudiable Verification Certificates with chained identity support.

## 5. Hybrid PQC Protocol (AgentV v1.6.2+)
In response to emerging quantum threats, AgentV v1.6.2 introduces a **Hybrid Post-Quantum Cryptographic (PQC)** stack for forensic signing, aligned with NIST's post-quantum standards.

### Cryptographic Foundation
- **Classical Layer**: Ed25519 (SHA-512 + Curve25519).
- **Post-Quantum Layer**: ML-DSA-65 (Module-Lattice-based Digital Signature Algorithm).
- **Hybrid Binding**: Signatures are chained within the `provenance_chain` of the VC v3.0.0 manifest.

### Zero-Exposure Signing (ZES)
To maintain the privacy of industrial evaluation data, AgentV implements **Zero-Exposure Signing (ZES)**:
1.  The evaluation trace and manifest are hashed locally using **SHAKE-256**.
2.  Only the resulting cryptographic digest is transmitted to the PQC signing provider (CycleCore).
3.  The raw trace data never leaves the project's security jail, ensuring zero leakage of proprietary trajectories.

### Policy Enforcement (Strict Mode)
Industrial environments can enforce quantum-safe compliance via `PQC_STRICT_MODE=true`. In this mode:
- Evaluations will be marked **NON-COMPLIANT** if PQC signing fails or the provider is unreachable.
- Cryptographic verification (`agentv verify`) will fail if a PQC signature is expected but cannot be validated.
- The `agentv run` and `agentv evaluate` commands support the `--pqc` flag for granular, per-run enforcement.

## 6. Practical Implementation
Developers should maintain this structure by:
1. Updating the versions in `pyproject.toml` and this document simultaneously.
2. Adding any new third-party dependency licenses to the `LICENSES/` directory.
3. Updating the [NOTICE](NOTICE) file when adding new dependencies.
4. Ensuring `shim_resources.json` contains no raw secrets; use `.local.json` or Environment Variables.
