---
title: Guide to Core Functions
description: A comprehensive reference of the 1,500+ granular tags used to classify agent tasks across 30+ industrial sectors.
---

To provide granular diagnostic analysis, every scenario in AgentV is tagged with a **Core Function** within its broader use case. This taxonomy ensures that failures are classified not just by sector (e.g., Finance), but by the specific skill required (e.g., Accounts Payable).

## 📊 High-Level Taxonomy

The AgentV core supports 1,800+ function identifiers across the following major sectors:

| Sector | Primary Focus | Key Use Cases |
| :--- | :--- | :--- |
| **Finance** | Regulatory & Transactional | Retail Banking, Wealth Mgmt, Corporate Finance |
| **Healthcare** | Clinical & Admin | Patient Admin, Clinical Care, Revenue Cycle |
| **Manufacturing** | Industrial & Supply | Production Scheduling, QA, Spares Mgmt |
| **Public Sector** | Citizen & Infrastructure | Benefits Admin, Licensing, Public Works |
| **Cybersecurity** | Defensive & Forensic | SecOps, Vulnerability Mgmt, IAM |
| **Legal** | Compliance & Litigation | Case Mgmt, Contracts, IP Mgmt |

---

## 📂 Detailed Function Registry

For a complete breakdown of every function and its success criteria, refer to the individual **Sector Guides** in the [Evaluator Persona](/evaluator/industries/).

### Common Cross-Sector Functions
While most functions are industry-specific, several recur across domains:

- **`Incident Management`**: Responding to faults or outages.
- **`Order Processing`**: Managing the lifecycle of a request or purchase.
- **`Compliance Reporting`**: Generating mandatory regulatory documentation.
- **`Customer/Citizen Support`**: Managing identity and general inquiries.

---

## 🛠️ Usage in AES Scenarios

In an **AES v1.4** scenario, the `core_function` tag is an **optional metadata field** used to enhance forensic diagnostics:

```json
{
  "metadata": {
    "industry": "Finance",
    "use_case": "Retail Banking",
    "core_function": "Fraud & Security"
  },
  "task": "Identify if the transaction at 03:00 UTC is suspicious."
}
```

The `TriageEngine` leverages this optional tag to correlate failures with historic performance benchmarks for that specific function. It is not required for scenario validation but is recommended for high-fidelity industrial tracking.

---

## 📝 Full Registry Reference

> [!NOTE]
> The complete 1,800-line registry is maintained in the [Sector Guide Repository](/evaluator/industries/). Below are several key highlights by industry.

### Agriculture
- **Planting & Seeding**: Variety selection and prescription generation.
- **Irrigation Management**: Soil moisture monitoring and water optimization.
- **Livestock Health**: Diagnosis and vaccination scheduling.

### Aerospace
- **Design & Engineering**: CAD/Stress analysis and aerodynamic modeling.
- **Testing & Certification**: FAA/EASA documentation and NDT planning.
- **Mission Design**: Orbital mechanics and trajectory analysis (Space Systems).

### Audit
- **ITGC Review**: Access control and change management auditing.
- **Vulnerability Assessment**: NIST evaluation and incident response plan review.
- **Process Efficiency**: Bottleneck identification and process mapping.

[See all 30+ Industrial Sectors...](/evaluator/industries/)
