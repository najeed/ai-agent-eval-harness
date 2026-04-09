---
title: Industrial Sector Taxonomy
description: Explore the 30+ industrial sectors and 1,800+ core functions supported by MultiAgentEval.
---

MultiAgentEval provides high-fidelity, industry-specific data extraction and behavioral benchmarks across a wide range of sectors. Each sector includes unique data sources, schemas, and [Core Functions](/ai-agent-eval-harness/builder/core-functions/).

## 🏗️ Core Industrial Sectors

| Sector | Status | Primary Data Sources |
| :--- | :--- | :--- |
| [**Finance**](./finance/) | **HARDENED** | SEC EDGAR, FRED, World Bank |
| [**Healthcare**](./healthcare/) | **HARDENED** | CMS, WHO, Clinical DB |
| [**Manufacturing**](./manufacturing/) | **HARDENED** | IndStat, US Census, MacroSim |
| [**Telecom**](./telecom/) | **HARDENED** | FCC, Ookla, ITU |
| **Public Sector** | **HARDENED** | US Census, UN Data, HUD |
| **Energy** | **STABLE** | EIA, IEA, SmartGrid Sim |
| **Transportation** | **STABLE** | BTS, IATA, Logistics Sim |

---

## 🔬 Cross-Sector Intelligence

For complex enterprise agents, MultiAgentEval supports cross-sector scenarios (e.g., a "Fintech" agent analyzing "Telecomm" infrastructure debt). All sectors share a unified [Standard Schema](/ai-agent-eval-harness/evaluator/aes-spec/) ensuring interoperability.

### Unified Standard Schema
Every industry record is normalized to the following fields:
- `entity_name`: The primary subject (Company, Facility, Region).
- `metric`: The specific data point (e.g., `net_income`, `mortality_rate`).
- `value`: The numerical or categorical reading.
- `region`: ISO-3 or granular geographic identifier.
- `industry_code`: Standardized codes (ISIC, NAICS, or CIK).
