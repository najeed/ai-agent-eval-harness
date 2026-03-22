# Finance Robustness & Verification Strategy

## 1. Industry-Specific Data Integrity
To ensure the Finance High-Signal (DHS) dataset is unimpeachable, we implement the following vertical-specific checks:

### Financial Consistency
*   **Balance Sheet Check**: `Assets == Liabilities + ShareholdersEquity` (within a 0.01% rounding tolerance).
*   **Income Statement Check**: `GrossProfit == Revenue - CostOfRevenue`.
*   **Cash Flow Check**: `NetChangeInCash == Operating + Investing + Financing`.

## 2. Verification Plan
### Level 1: Unit Tests
*   Test XBRL parsers against edge-case filings (e.g., companies with complex debt structures).
*   Test FRED time-series alignment with off-cycle fiscal year ends.

### Level 2: Integration Tests
*   Mock SEC/FRED APIs to ensure the `Orchestrator` handles timeouts and rate limits correctly.

### Level 3: Human-in-the-Loop
*   Randomly sample 5% of extracted financial values and cross-check against the original PDF/HTML source using OCR/Vision or manual auditor review.
