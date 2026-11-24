---
title: Finance Sector
description: High-fidelity financial data extraction and auditing for AI agents.
---

The Finance sector is the foundational "Anchor" for the AgentV engine, providing gold-standard XBRL and macro indicators for benchmarking financial agents.

## 📊 Status: **Provider-dependent coverage**

- **Architecture**: SEC EDGAR & FRED Multi-Source Layer.
- **Verification**: Validate the selected source and output records for this run; no universal live-source parity guarantee is implied.

## 📡 Data Sources

The sources below describe reference datasets and task models. Actual connectivity
depends on the implemented provider, credentials and supplied input files.
Simulation is disabled by default; enable `--allow-simulation` deliberately and
retain `simulation`/`execution_mode` provenance. A listed source is not proof
that its live API was used or that all records match it.


| Source | Description |
| :--- | :--- |
| **SEC EDGAR** | Direct XBRL factual extraction for public companies. |
| **FRED** | Federal Reserve Economic Data (Macroeconomic indicators). |
| **World Bank** | Global financial depth and GDP statistics. |

---

## 🛠️ Industry Schema

Finance-specific records are normalized to the `StandardSchema` with these key mappings:

- `entity_name`: Company (e.g., "Apple Inc.") or Country.
- `metric`: `total_assets`, `net_income`, `gdp_growth`, or `credit_risk_score`.
- `cik`: (SEC Only) Central Index Key for mapping.
- `value`: Precise numerical reading.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Portfolio Management**: Asset allocation and risk profiling.
- **Fraud & Security**: Suspicious activity detection and KYC validation.
- **Retail Banking**: Account servicing, loans, and credit adjustments.

[Explore all 1,800+ Core Functions](/builder/core-functions/)
