---
title: Healthcare Sector
description: Clinical and institutional healthcare metrics for agent evaluation.
---

The Healthcare sector provides critical signals for medical research and hospital management agents, focusing on clinical veracity and regulatory compliance.

## 🏥 Status: **HARDENED**

- **Architecture**: CMS & Clinical Database Simulation Layer.
- **Verification**: 100% Parity with audited clinical simulators.

## 📡 Data Sources

| Source | Description |
| :--- | :--- |
| **CMS** | Centers for Medicare & Medicaid Services (Institutional metrics). |
| **WHO** | World Health Organization Global Health Observatory. |
| **Clinical Database** | Audited clinical record simulators for HIPAA-compliant testing. |

---

## 🛠️ Industry Schema

Healthcare records utilize specialized fields for clinical context:

- `facility_name`: Hospital, Laboratory, or Care Center identifier.
- `metric`: `readmission_rate`, `patient_satisfaction`, or `mortality_index`.
- `drg_code`: (Optional) Diagnosis Related Group mapping for billing accuracy.
- `value`: Numerical or categorical clinical reading.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Patient Administration**: Intake, scheduling, and billing lifecycle.
- **Clinical Care**: Treatment planning and diagnostic interpretation.
- **Revenue Cycle**: HIPAA-compliant claim processing and auditing.

[Explore all 1,800+ Core Functions](/builder/core-functions/)
