# Robustness & Verification Strategy

## 1. Data Integrity (The "Unimpeachable" Core)
To ensure the dataset is factual and reliable, we implement the following automated checks:

### Financial Consistency (Finance Pilot)
*   **Balance Sheet Check**: `Assets == Liabilities + ShareholdersEquity` (within a 0.01% rounding tolerance).
*   **Income Statement Check**: `GrossProfit == Revenue - CostOfRevenue`.

### Intelligence Validation
*   **LLM Verification**: Every record extracted via LLM is subjected to a domain-integrity check (e.g., non-negative revenue) before being committed to the dataset.
*   **Fuzzy Identity Resolution**: Uses `rapidfuzz` to ensure that entities are matched across verticals with a confidence score > 85%, preventing signal leakage from unrelated entities.

## 2. Robustness Features
*   **Circuit Breaker**: Detects repeated failures (e.g., API 500s or 429s) and trips to prevent cascading exhaustion of resources.
*   **Exponential Backoff**: Automatic retries with randomized jitter to handle transient network instability gracefully.
*   **Autonomous PII Scrubbing**: A regex-based engine in the `BaseProvider` cleans emails, phone numbers, and sensitive identifiers from raw unstructured text *before* it reaches the LLM inference tier.
*   **Immutable Checksums**: All records are now secured with a SHA-256 hash of their content, ensuring data-aware integrity throughout the pipeline.
*   **Aggressive Rate Limiting**: The orchestrator enforces per-source rate limits (e.g., 10 req/s for SEC) with a global "cooldown" phase.

## 3. Verification Plan
### Level 1: Unit Tests
*   Test XBRL parsers and PDF extractors against edge-case artifacts.
*   Verify regex heuristic coverage for structured KV data.

### Level 2: Integration Tests
*   Verify cross-industry correlation (e.g., matching a Telecom record to a Finance filing automatically).
*   Test the `--overwrite` flag for stable CI/CD automation.

### Level 3: Human-in-the-Loop
*   Sample 5% of extracted values and cross-check against the original source using OCR or manual review.
