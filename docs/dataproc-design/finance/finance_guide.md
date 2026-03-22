# 🏦 Finance Sector: Deep-Dive Guide

## 🛰️ Data Source Strategy
The finance sector provides the "Gold Standard" for audited, factual benchmarks.

### 1. SEC EDGAR (Corporate Fundamentals)
*   **Role**: Primary source for audited financial reports (10-K, 10-Q).
*   **Logic**: 
    *   Fetch **XBRL** versions for structured table parsing.
    *   Target core facts: `Revenues`, `Net Income`, `Total Assets`, `Total Liabilities`.
    *   **Rate-Limiting**: Strictly 10 requests/second to prevent IP blocking.
*   **Verification**: Adheres to the accounting identity: `Assets = Liabilities + Equity`.

### 2. FRED (Federal Reserve Economic Data)
*   **Role**: Macroeconomic context for longitudinal analysis.
*   **Key Series**:
    *   `FEDFUNDS`: Cost of capital context.
    *   `CPIAUCSL`: Inflationary impact on corporate margins.
    *   `GDP`: Global growth correlation.

## 🛠️ ETL & Transformation
1.  **XBRL Parsing**: Convert nested XML tags into flat JSON for agency consumption.
2.  **Normalization**: Standardize fiscal periods to ISO-8601; normalize currency to USD.
3.  **Reasoning Injection**: 
    *   **R&D Intensity**: `R&D Spend / Total Revenue`.
    *   **Debt Coverage**: `Interest Expense / Operating Income`.

## 🛡️ Robustness & Paywalls
*   **Why Open Sources?**: SEC and FRED are unimpeachable "Sources of Truth." Intermediaries like Bloomberg or S&P derive their data from these filings; by going direct, we eliminate derivation error.
*   **Compliance**: Shipped datasets use **Synthetic Templates** ("Frank Corp", "Leo Corp") to ensure zero-redistribution of restricted records while maintaining schema honesty.
*   **Fallback**: High-fidelity simulation based on [UCI Credit Approval](https://archive.ics.uci.edu/dataset/27/credit+approval) benchmarks is active for CI/CD environments.

## 🧪 Reasoning Challenges for Agents
*   "Compare Ticker A's R&D intensity vs Ticker B over 3 fiscal years."
*   "Identify the top 3 risk factors in the 10-K directly impacted by a +50bps rate hike."
*   "Summarize the correlation between Q3 Net Income and the Fed Funds Rate of the same period."
