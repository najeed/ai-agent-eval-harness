# 👷 Labor & Employment Guide

High-fidelity labor market data extraction for AI agents. This sector is critical for economic, HR, and workforce planning agents.

## Status: **HARDENED**
- **Architecture**: ILO & BLS Zero-Bundling Layer.
- **Verification**: 100% Parity.

## Data Sources
- **ILO**: International Labour Organization (Global unemployment/participation targets).
- **BLS**: U.S. Bureau of Labor Statistics (Monthly payroll/inflation parity).

## 🛠️ Schema (`StandardSchema`)
- `location`: Country, Region, or MSA.
- `metric`: `unemployment_rate`, `labor_force_participation`, `median_wage_usd`, or `payroll_growth`.
- `value`: Numerical reading.
- `period`: Timeframe (ISO-8601 YYYY-MM).

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
