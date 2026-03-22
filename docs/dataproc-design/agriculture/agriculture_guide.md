# 🌽 Agriculture Sector: Deep-Dive Guide

## 🛰️ Data Source Strategy
The agriculture sector focuses on commodity yield, state-level pricing, and crop volatility.

### 1. USDA NASS (Quick Stats)
*   **Role**: Primary source for U.S. agricultural production and pricing.
*   **Logic**:
    *   Fetch **REST API** payloads or CSV exports.
    *   Target Commodities: `CORN`, `SOYBEANS`, `WHEAT`.
    *   **State-Level Aggregation**: Track state performance against national averages.

### 2. FAOSTAT (Global Context)
*   **Role**: Global benchmarks for food security.
*   **Logic**:
    *   **BYOD Strategy**: Provided links for international yield data.
    *   **Reasoning Injection**: Correlate weather-driven yield loss with commodity price hikes.

## 🛠️ ETL & Transformation
1.  **Commodity Normalization**: Standardize pricing to `Price per Bushel`.
2.  **Yield Modeling**: Calculate `Production / Harvested Area` benchmarks.
3.  **State Logic**: Handle state-specific fiscal reporting cycles.

## 🛡️ Robustness & Compliance
*   **Provenance**: Tagged with USDA NASS dataset identifier for veracity.
*   **Integrity**: SHA-256 deterministic hashing of state yield reports.
*   **Fallback**: High-fidelity USDA-style simulation active for offline execution.
