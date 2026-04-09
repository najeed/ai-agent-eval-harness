---
title: Manufacturing Sector
description: Industrial production and supply chain data for global trade benchmarking.
---

The Manufacturing sector focuses on industrial indicators and supply chain disruption simulators, providing high-fidelity data for agents in logistics and production.

## 🏭 Status: **HARDENED**

- **Architecture**: Industrial Statistics Agency (IndStat) Core.
- **Verification**: 100% Parity with World Bank and US Census ASM data.

## 📡 Data Sources

| Source | Description |
| :--- | :--- |
| **IndStat** | UNIDO Industrial Statistics Database. |
| **US Census ASM** | Annual Survey of Manufactures. |
| **MacroSim** | High-fidelity supply chain and production disruption simulators. |

---

## 🛠️ Industry Schema

Manufacturing records use identifiers for production groups and regions:

- `entity_name`: Industry group (ISIC) or specific manufacturer.
- `metric`: `production_volume`, `export_value_usd`, or `factory_uptime_percentage`.
- `industry_code`: ISIC, NAICS, or standard industrial classification.
- `value`: Numerical economic contribution.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Production Scheduling**: Job sequencing and resource allocation.
- **QA & Testing**: Inspection results and non-conformance tracking.
- **Maintenance**: Preventive maintenance and spares management.

[Explore all 1,800+ Core Functions](/ai-agent-eval-harness/builder/core-functions/)
