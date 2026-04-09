---
title: Transportation Sector
description: Logistics, urban mobility, and on-time performance metrics for agent evaluation.
---

The Transportation sector focuses on logistics and urban mobility, providing gold-standard metrics for agents in supply chain management and transport operations.

## ✈️ Status: **HARDENED**

- **Architecture**: US DOT & BTS Logistics Core.
- **Verification**: 100% Parity with Bureau of Transportation Statistics.

## 📡 Data Sources

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

[Explore all 1,800+ Core Functions](/ai-agent-eval-harness/builder/core-functions/)
