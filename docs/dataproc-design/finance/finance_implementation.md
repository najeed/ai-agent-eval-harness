# Finance Implementation Plan

This plan details the implementation of the Finance pilot using the `dataproc-engine` framework.

## Data Sources
*   **SEC EDGAR**: Primary source for audited corporate fundamentals (10-K, 10-Q).
*   **FRED**: Primary source for macroeconomic indicators (GDP, CPI, Interest Rates).

## Component Breakdown
1.  **FinanceProvider**:
    *   **SEC Extractor**: Handles 10-req/s rate limiting and XBRL parsing.
    *   **FRED Extractor**: Handles time-series alignment with fiscal periods.
2.  **Transformation Logic**:
    *   Maps XBRL tags to a normalized `Liquidity`, `Profitability`, and `Debt` schema.
    *   Pairs corporate metrics with period-avg macro data.

## Reasoning Tasks
1.  **Metric Comparison**: Cross-ticker R&D intensity analysis.
2.  **Macro Correlation**: Correlating net income growth with GDP trends.
3.  **Risk Analysis**: Impact of interest rate hikes on specific corporate risk factors.
