---
title: Public Sector
description: Demographics, environment, labor, and housing metrics for societal and economic analysis.
---

The Public Sector category consolidates high-fidelity societal and economic indicators, providing the foundational context for evaluating agents in governance, social services, and environmental resilience.

## 🏛️ Status: **HARDENED**

- **Architecture**: Multi-Source Integration (World Bank, UN, US Census).
- **Verification**: 100% Parity with authoritative global and national sources.

---

## 🌍 Demographics
Foundational population and social indicators.
- **Data Sources**: World Bank Global Indicators, US Census ACS.
- **Metrics**: `population_total`, `median_age`, `literacy_rate`, `urban_population_percentage`.

## 🌿 Environment & Climate
Critical signals for ESG, insurance risk, and resilience auditing.
- **Data Sources**: NOAA Climate Data Online, Copernicus Store, USGS Simulators.
- **Metrics**: `air_temperature`, `precipitation_mm`, `co2_concentration_ppm`, `sea_level_rise_mm`.

## 👷 Labor & Employment
Workforce planning and economic activity monitoring.
- **Data Sources**: ILO (Global), U.S. BLS (National payrolls).
- **Metrics**: `unemployment_rate`, `labor_force_participation`, `median_wage_usd`, `payroll_growth`.

## 🏠 Housing & Infrastructure
Urban development and infrastructure access indicators.
- **Data Sources**: U.S. HUD, World Bank Infrastructure.
- **Metrics**: `rent_2br`, `access_rate_electricity`, `affordable_housing_index`.

---

## 🛠️ Unified Industry Schema

Public Sector records are normalized to standard geographic and temporal granularities:

- `region`: Country (ISO-3), State, or City.
- `metric`: The specific indicator (e.g., `unemployment_rate`).
- `period`: ISO-8601 observation window (e.g., `2024-Q1`).
- `value`: Numerical reading.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Administration**: Records management, licensing, and public reporting.
- **Regulatory & Compliance**: Environmental auditing, labor law enforcement.
- **Human Services**: Benefits administration and case management.

[Explore all 1,800+ Core Functions](/ai-agent-eval-harness/builder/core-functions/)
