# ⚡ Energy Guide

High-fidelity energy production and pricing metrics for AI agents. This sector provides essential signals for infrastructure and grid management agents.

## Status: **HARDENED**
- **Architecture**: EIA & Energy Provider Agency Spatio-Temporal Tracking.
- **Verification**: 100% Parity.

## Data Sources
- **EIA**: U.S. Energy Information Administration (REST API integration).
- **Energy Provider Agency**: International Energy Agency (Global energy balances parity).

## 🛠️ Schema (`StandardSchema`)
- `location`: Grid node, Country, or Station identifier.
- `metric`: `generation_mwh`, `price_per_kwh_usd`, or `carbon_intensity`.
- `value`: Numerical reading.
- `source_type`: `wind`, `solar`, `nuclear`, `fossil`, etc.

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
