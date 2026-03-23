# 🌍 Demographics Guide

High-fidelity population and social indicator data extraction. This sector provides the base foundation for contextualizing all other industrial signals.

## Status: **HARDENED**
- **Architecture**: World Bank Population Core.
- **Verification**: 100% Parity.

## Data Sources
- **World Bank**: Global Population & Social Indicators API.
- **US Census**: State-level demographic indicators and ACS simulators.

## 🛠️ Schema (`StandardSchema`)
- `region`: Country (ISO-3), State, or City granularity.
- `metric`: `population_total`, `median_age`, `literacy_rate`, or `urban_population_percentage`.
- `value`: Numerical reading.
- `year`: Observation year (ISO-8601 YYYY).

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
