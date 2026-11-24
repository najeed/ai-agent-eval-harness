---
title: Transportation Sector
description: Logistics, urban mobility, and on-time performance metrics for agent evaluation.
---

The Transportation sector focuses on logistics and urban mobility, providing gold-standard metrics for agents in supply chain management and transport operations.

## ✈️ Status: **Provider-dependent coverage**

- **Architecture**: US DOT & BTS Logistics Core.
- **Verification**: Validate the selected source and output records for this run; no universal live-source parity guarantee is implied.

## 📡 Data Sources

The sources below describe reference datasets and task models. Actual connectivity
depends on the implemented provider, credentials and supplied input files.
Simulation is disabled by default; enable `--allow-simulation` deliberately and
retain `simulation`/`execution_mode` provenance. A listed source is not proof
that its live API was used or that all records match it.


| Source | Description |
| :--- | :--- |
| **DOT / BTS** | Bureau of Transportation Statistics (On-time performance). |
| **OSM** | OpenStreetMap (Geospatial parity and routing metrics). |
| **Logistics Sim**| High-fidelity port and air-cargo bottleneck simulators. |

---

## 🛠️ Industry Schema

Transportation records track carriers and pairwise location logistics:

- `carrier`: Airline name, Rail ID, or Fleet identifier.
- `metric`: `arrival_delay_minutes`, `cancellation_rate`, or `ton_miles_logistics`.
- `origin_dest`: Pairwise location identifiers for routing analysis.
- `value`: Numerical reading.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Freight & Logistics**: Dispatching, route optimization, and shipment tracking.
- **Urban Mobility**: Public transit scheduling and traffic management.
- **Aviation**: Flight operations, crew scheduling, and safety auditing.

[Explore all 1,800+ Core Functions](/builder/core-functions/)
