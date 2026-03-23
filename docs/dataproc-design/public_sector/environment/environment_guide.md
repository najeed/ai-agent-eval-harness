# 🌿 Environment & Climate Guide

High-fidelity environment and climate data extraction for AI agents. This sector provides critical signals for ESG, insurance risk, and supply chain resilience agents.

## Status: **HARDENED**
- **Architecture**: Spatio-Temporal Tracking.
- **Verification**: 100% Parity.

## Data Sources
- **NOAA**: Climate Data Online (TMAX, TMIN, PRCP).
- **Copernicus**: EU Climate Data Store (Atmospheric monitoring).
- **USGS**: Water and seismic data simulators.

## 🛠️ Schema (`StandardSchema`)
- `location`: Geographic coordinates, Station ID, or Zip Code.
- `timestamp`: UTC observation ISO-8601.
- `metric`: `air_temperature`, `precipitation_mm`, `co2_concentration_ppm`, or `sea_level_rise_mm`.
- `value`: Numerical reading.
- `reliability_score`: Signal-to-noise ratio from sensor clusters.

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
