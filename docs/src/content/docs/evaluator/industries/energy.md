---
title: Energy Sector
description: Energy production, pricing, and carbon intensity metrics for grid management agents.
---

The Energy sector provides essential signals for infrastructure and grid management agents, tracking production, spatial-temporal pricing, and sustainability metrics.

## ⚡ Status: **Provider-dependent coverage**

- **Architecture**: EIA & IEA Spatio-Temporal Tracking Layer.
- **Verification**: Validate the selected source and output records for this run; no universal live-source parity guarantee is implied.

## 📡 Data Sources

The sources below describe reference datasets and task models. Actual connectivity
depends on the implemented provider, credentials and supplied input files.
Simulation is disabled by default; enable `--allow-simulation` deliberately and
retain `simulation`/`execution_mode` provenance. A listed source is not proof
that its live API was used or that all records match it.


| Source | Description |
| :--- | :--- |
| **EIA** | U.S. Energy Information Administration (REST API). |
| **IEA** | International Energy Agency (Global energy balances parity). |
| **SmartGrid Sim** | Internal simulators for grid stability and load balancing scenarios. |

---

## 🛠️ Industry Schema

Energy records focus on grid nodes and production sources:

- `location`: Grid node, Country, or Station identifier.
- `metric`: `generation_mwh`, `price_per_kwh_usd`, or `carbon_intensity`.
- `source_type`: `wind`, `solar`, `nuclear`, `fossil`, etc.
- `value`: Numerical reading for the specified metric.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Grid Operations**: Real-time monitoring, control, and fault isolation (FLISR).
- **Service Orders**: Field service requests, low pressure, and meter checks.
- **Sustainability**: Conservation efficiency and energy-saving program management.

[Explore all 1,800+ Core Functions](/builder/core-functions/)
