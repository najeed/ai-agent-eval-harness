# dataproc High-Signal (DHS) Dataset Specification

## Overview
The dataproc High-Signal (DHS) dataset is designed to provide unimpeachable, factual, and high-signal data for evaluating AI agents in complex financial tasks. It combines corporate transparency data (SEC) with macroeconomic indicators (FRED).

## Data Sources

## Detailed Pilot Schema (Finance)

### 1. Corporate Fundamentals (SEC)
*   **Source**: Audited 10-K/Q XBRL filings.
*   **Fields**:
    *   `liquidity_metrics`: Current Ratio, Quick Ratio.
    *   `profitability_metrics`: Gross Margin, Operating Margin, ROE.
    *   `debt_structure`: Long-Term Debt, Interest Coverage.

### 2. Macro Context (FRED)
*   **Source**: Federal Reserve Bank of St. Louis.
*   **Fields**:
    *   `period_avg_cpi`: Inflationary context of the fiscal period.
    *   `fed_funds_rate`: Cost of capital context.

### 3. Reasoning & QA Pairs (High-Signal)
*   **Objective**: Test agentic reasoning beyond simple retrieval.
*   **Task Examples**:
    *   "Compare Ticker A's R&D intensity (R&D spend / Revenue) against Ticker B over the last 3 fiscal periods."
    *   "Correlate Ticker C's Net Income growth with the Real GDP growth rate in the same quarter."
    *   "Summarize the 'Risk Factors' section and identify the top 3 items that could be directly impacted by a +50bps rate hike."

## dataproc Framework "Generic Ready" Features
*   **Schema Inheritance**: All industry datasets share a common `BaseSchema` (metadata, source_url, timestamp, checksum).
*   **Modular Transformation**: The "Reasoning" engine is decoupled from the data extraction, allowing us to swap the extraction stage for a new industry (e.g., Transit) while keeping the same evaluation logic.

## Quality Guarantees
*   **Verifiable**: Each data point includes a direct URL to the source (e.g., SEC filing URL).
*   **Normalized**: Numerical data is converted to consistent units (USD).
*   **Temporal Alignment**: Company results are paired with the economic conditions of that specific period.
