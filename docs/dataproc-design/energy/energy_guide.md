# ⚡ Energy Sector: Deep-Dive Guide

## 🛰️ Data Source Strategy
The energy sector tracks global production, pricing volatility, and grid transitions.

### 1. EIA (U.S. Energy Information Administration)
*   **Role**: Primary source for WTI/Brent pricing and national production stats.
*   **Logic**:
    *   Fetch **REST API** series (Series IDs: `PET.RWTC.D` for WTI).
    *   Track historical price volatility and storage volume.
    *   **Resiliency**: Circuit breaker logic for API service availability.

### 2. IEA (International Energy Agency)
*   **Role**: Global benchmarks for energy balances.
*   **Logic**:
    *   **Gated Source**: Redistribution prohibited; BYOD strategy active.
    *   **Zero-Mock Simulation**: Ships with `IEA-BALANCE-SIM` for logic testing.
    *   **Reasoning Injection**: Model the impact of price volatility on renewable grid investment.

## 🛠️ ETL & Transformation
1.  **Time-Series Normalization**: Align daily price indices with monthly production benchmarks.
2.  **Unit Conversion**: Standardize to Barrel (BBL) and Thousand Cubic Feet (MCF).
3.  **Volatility Scoring**: LLM-driven analysis of energy market sentiment.

## 🛡️ Robustness & Safety
*   **Provenance**: Every entry is tagged with its EIA series ID for auditability.
*   **Integrity**: SHA-256 hashing ensures that time-series snapshots remain immutable during evaluation.
*   **Fallback**: High-fidelity simulation based on IEA global energy balances.
