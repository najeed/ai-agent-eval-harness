# Financial Data Source Analysis: Public vs. Paywalled

## Restricted/Paywalled Sources Considered

| Source | Strength | Cost/Access | Recommendation |
| :--- | :--- | :--- | :--- |
| **Bloomberg Terminal** | Real-time news, private company data, proprietary analytics. | ~$24,000/year per user. | **Exclude** from primary ETL. Only use as a "gold standard" for manual cross-checks. |
| **Reuters (Eikon)** | Deep historical news and institutional-grade financial data. | High (thousands per year). | **Exclude**. Similar data available via SEC for public companies. |
| **S&P Capital IQ** | Exceptional for standardized financials and industry-specific metrics. | High. | **Exclude** for automation to ensure the dataset remains portable and open. |
| **Alpha Vantage / Polygon.io** | Easy API access for market prices. | Freemium (limited requests). | **Secondary**. Used only if real-time price alignment is needed. |

## Why Open Sources (SEC/FRED) are Prioritized

1.  **Unimpeachability**: SEC filings are the "Source of Truth." Even Bloomberg and S&P derive their data from these filings. By going directly to the source, we eliminate intermediary errors.
2.  **Factual Authority**: Government-published data (SEC, FRED) is the legal standard for financial reporting and economic measure.
3.  **Reproducibility**: Any user can verify the dataset's accuracy by visiting `sec.gov` or `stlouisfed.org` without a paid subscription.
4.  **License Compliance**: Public data avoids the restrictive terms-of-service often found in commercial data providers or third-party benchmark collections. By distributing the *extraction logic* rather than the *data*, we ensure the framework remains legally compliant while providing the same high-signal utility.

## High-Quality Alternatives
*   **HuggingFace (FinanceBench)**: Good for benchmarking, but lacks the raw, comprehensive narrative sections (entire 10-K) we plan to include.
*   **OpenBB**: An excellent open-source alternative that we may use as a library to facilitate access to multiple public sources.
