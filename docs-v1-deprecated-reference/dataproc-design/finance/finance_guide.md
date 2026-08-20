# 💰 Finance Guide

High-fidelity financial data extraction for AI agents. This sector is the foundational "Anchor" for the engine, providing gold-standard XBRL and macro indicators.

## Status: **HARDENED**
- **Architecture**: SEC EDGAR & FRED Multi-Source Layer.
- **Verification**: 100% Parity.

## Data Sources
- **SEC EDGAR**: Direct XBRL factual extraction.
- **FRED**: Federal Reserve Economic Data (Macro indicators).
- **World Bank**: Global financial depth indicators.

## 🛠️ Schema (`StandardSchema`)
- `entity_name`: Company or Country.
- `metric`: `total_assets`, `net_income`, `gdp_growth`, or `credit_risk_score`.
- `value`: Numerical reading.
- `cik`: (SEC Only) Central Index Key.

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
