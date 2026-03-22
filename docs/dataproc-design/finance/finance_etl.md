# FHS Dataset ETL Strategy

## Pipeline Architecture
The ETL (Extract, Transform, Load) process is designed for high reliability and adherence to institutional data access rules.

### 1. Extraction (E)
*   **SEC EDGAR**:
    *   Use the `sec-api.io` or `edgar` Python library.
    *   Implement **strict rate-limiting** (10 requests per second) to prevent IP blocking by the SEC.
    *   Fetch XBRL (eXtensible Business Reporting Language) versions for structured financial tables.
*   **FRED**:
    *   Use `fredapi`.
    *   Fetch full time series to calculate rolling averages and period-over-period changes.

### 2. Transformation (T)
*   **XBRL Parsing**: Convert nested XML/XBRL tags into flat JSON structures for Balance Sheets and Income Statements.
*   **NLP Text Extraction**: Strip HTML boilerplate from narrative sections (Risk Factors, MD&A) using `BeautifulSoup` and specialized regex for SEC formatting.
*   **Normalization**: Standardize date formats (ISO-8601) and currency units (millions vs. billions).

### 3. Loading (L)
*   **Storage**: Parquet for large-scale time-series data; JSONL for unstructured narrative data.
*   **Versioning**: Semantic versioning for the dataset (e.g., v1.0.0 for 2023 data).

## Robustness Features
*   **Retry Logic**: Exponential backoff for 429 (Too Many Requests) or 503 (Service Unavailable) errors.
*   **Checksums**: Store SHA-256 hashes of raw source files to detect upstream modifications.
*   **Validation**:
    *   Check that `Assets = Liabilities + Equity`.
    *   Verify that `Net Income` matches derived values from revenues and expenses.

## Automation
*   **GitHub Actions / Cron**: Scheduled quarterly updates to pull the latest 10-Q/10-K filings.
*   **Incident Alerts**: Integration with Slack/Email if extraction failure rate exceeds 5%.
