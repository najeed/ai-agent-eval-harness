---
title: Agriculture Sector
description: Global crop production and trade metrics for food security analysis.
---

The Agriculture sector provides essential signals for food security and commodity trading agents, tracking global production volumes and yields.

## 🚜 Status: **Provider-dependent coverage**

- **Architecture**: USDA & FAO Universal Production Layer.
- **Verification**: Validate the selected source and output records for this run; no universal live-source parity guarantee is implied.

## 📡 Data Sources

The sources below describe reference datasets and task models. Actual connectivity
depends on the implemented provider, credentials and supplied input files.
Simulation is disabled by default; enable `--allow-simulation` deliberately and
retain `simulation`/`execution_mode` provenance. A listed source is not proof
that its live API was used or that all records match it.


| Source | Description |
| :--- | :--- |
| **USDA NASS** | National Agricultural Statistics Service (US production). |
| **FAOStat** | Food and Agriculture Organization of the UN (Global stats). |
| **MODIS** | Satellite-derived crop health and yield projections. |

---

## 🛠️ Industry Schema

Agriculture records focus on commodities and seasonal readings:

- `commodity`: Crop name (e.g., "CORN", "WHEAT") or item group.
- `metric`: `yield_per_acre`, `production_tonnes`, or `export_value`.
- `unit`: Standard measure (e.g., BU/ACRE, MT).
- `year`: The specific growing season or calendar year.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Resource Modeling**: Soil health analysis and variety selection.
- **Supply & Logistics**: Procurement, ordering, and inbound management.
- **Food Safety**: Traceability and global compliance auditing.

[Explore all 1,800+ Core Functions](/builder/core-functions/)
