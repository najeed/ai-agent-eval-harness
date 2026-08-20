# 🏭 Manufacturing Guide

High-fidelity industrial production and supply chain data extraction. This guide focuses on World Bank/Industrial Statistics Agency level industrial indicators for benchmarking global trade.

## Status: **HARDENED**
- **Architecture**: Industrial Statistics Agency IndStat Core.
- **Verification**: 100% Parity.

## Data Sources
- **Industrial Statistics Agency**: Industrial Statistics Database (IndStat).
- **US Census**: Annual Survey of Manufactures (ASM).
- **MacroSim**: Supply chain disruption simulators.

## 🛠️ Schema (`StandardSchema`)
- `entity_name`: Industry group (ISIC) or specific company.
- `metric`: `production_volume`, `employees_total`, `export_value_usd`, or `factory_uptime_percentage`.
- `value`: Numerical reading.
- `region`: Global (ISO-3) or state-level granularity.
High-fidelity industrial production data extraction for AI agents.

## Data Sources
- **Industrial Statistics Agency**: Industrial Statistics.
- **US Census**: Annual Survey of Manufactures (ASM).

## Schema
- `industry_code`: ISIC or NAICS code.
- `value_added`: Economic contribution.
- `employment`: Workforce count.

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
