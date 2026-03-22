# Generic Robustness & Verification Strategy

## 1. Data Integrity (The "Unimpeachable" Core)
To ensure the dataset is factual and reliable, we implement the following automated checks:

### Industry-Specific Consistency
*   **Logical Audits**: Each provider must implement domain-specific logical checks (e.g., in Finance: Assets = Liabilities + Equity).

### Technical Validation (Generic Framework)
*   **Checksum Verification**: Every raw artifact fetched (HTML, XML, JSON) is hashed using SHA-256. If a re-run produces a different hash for the same ID, it is flagged for manual review.
*   **Schema Enforcement**: Use `pydantic` models to ensure that every `BaseProvider` output strictly adheres to the `StandardIndustrySchema`.

## 2. Robustness Features
*   **Aggressive Rate Limiting**: The orchestrator enforces per-source rate limits with a global "cooldown" phase if 429 errors are detected.
*   **Fault-Tolerant Extraction**: If one item fails, the engine logs the error, continues with the rest of the batch, and provides a "Dead Letter Queue" for retries.
*   **Self-Documentation**: Every record includes a `provenance` block containing `source_url`, `retrieval_timestamp`, and `engine_version`.

## 3. Verification Plan
### Level 1: Unit Tests
*   Test source-specific parsers against edge-case artifacts.
*   Test data alignment logic for multi-source providers.

### Level 2: Integration Tests
*   Mock external APIs to ensure the `Orchestrator` handles timeouts and rate limits correctly.
*   Verify that a "DummyProvider" can be added and executed without core code changes.

### Level 3: Human-in-the-Loop
*   Randomly sample a percentage of extracted values and cross-check against the original source artifacts.
