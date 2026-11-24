---
title: Education & EdTech Sector
description: Institutional statistics and personal learning trajectories for educational agents.
---

The Education sector covers both traditional institutional statistics (enrollment, graduation) and high-granularity EdTech behavioral data for personal learning assistant evaluation.

## 📚 Status: **Provider-dependent coverage**

- **Architecture**: Zero-Touch Institutional Reporting Layer.
- **Verification**: Validate the selected source and output records for this run; no universal live-source parity guarantee is implied.

## 📡 Data Sources

The sources below describe reference datasets and task models. Actual connectivity
depends on the implemented provider, credentials and supplied input files.
Simulation is disabled by default; enable `--allow-simulation` deliberately and
retain `simulation`/`execution_mode` provenance. A listed source is not proof
that its live API was used or that all records match it.


| Source | Description |
| :--- | :--- |
| **NCES** | U.S. National Center for Education Statistics (API). |
| **UNESCO** | Global literacy and enrollment observatory indicators. |
| **EdTech** | High-fidelity synthetic learning trajectories (Kaggle/Coursera parity). |

---

## 🛠️ Industry Schema

Education records focus on institution types and demographic slices:

- `institution`: School name, University ID, or EdTech Platform.
- `metric`: `graduation_rate`, `enrollment_total`, `course_completion`.
- `demographic_slice`: (Optional) Slice by ethnicity, gender, or income.
- `value`: Numerical reading.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Assessment & Grading**: Test generation, automated grading, and feedback.
- **Content Operations**: Curriculum planning and resource management.
- **Student Services**: Enrollment, transcript management, and advising.

[Explore all 1,800+ Core Functions](/builder/core-functions/)
