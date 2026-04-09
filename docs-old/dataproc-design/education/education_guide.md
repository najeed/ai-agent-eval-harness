# 📚 Education & EdTech Guide

High-fidelity education data extraction for AI agents. This guide covers both traditional Institutional statistics (NCES) and personal learning trajectories (EdTech).

## Status: **HARDENED**
- **Architecture**: Zero-Bundling Compliant.
- **Verification**: 100% Parity.

## Data Sources
- **NCES**: U.S. National Center for Education Statistics (API-compatible).
- **UNESCO**: Institute for Statistics (Global enrollment/literacy parity).
- **EdTech**: Synthetic Coursera/Kaggle learning trajectories for AI behavior modeling.

## 🛠️ Schema (`StandardSchema`)
- `institution`: School name, University ID, or Platform.
- `metric`: `graduation_rate`, `enrollment_total`, `retention_index`, or `course_completion`.
- `value`: Numerical reading.
- `demographic_slice`: (Optional) Slice by ethnicity, gender, or income.

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
