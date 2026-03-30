# 🚜 Agriculture Guide

High-fidelity crop production and global trade metrics for AI agents. This sector provides essential signals for food security and commodity trading agents.

## Status: **HARDENED**
- **Architecture**: USDA & FAO Universal Production Layer.
- **Verification**: 100% Parity.

## Data Sources
- **USDA**: National Agricultural Statistics Service (NASS API).
- **FAO**: Food and Agriculture Organization (FAOStat Global).

## 🛠️ Schema (`StandardSchema`)
- `commodity` / `item`: Crop name (e.g., CORN) or Global item.
- `year`: Integer reading (e.g., 2023).
- `yield_value` / `value`: Numerical reading (e.g., 180.5).
- `unit`: Unit of measure (e.g., BU / ACRE, tonnes).
- `location`: Geographic granularity (e.g., IA, World).

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
