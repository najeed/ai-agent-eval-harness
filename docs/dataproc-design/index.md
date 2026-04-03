# Dataproc Engine

The **dataproc-engine** is an enterprise-grade framework designed to generate high-fidelity industrial datasets for AI agent evaluation. By consolidating 16 distinct sectors into a unified hierarchical fleet, the engine provides a robust foundation for benchmarking agents across finance, healthcare, energy, the public sector, and more.

## 🛡️ Core Pillars

1.  **Zero-Bundling Architecture**: Guarantees that no PII or restricted commercial records are leaked into the evaluation stream, leveraging high-fidelity simulations where necessary.
2.  **Industrial Parity**: Achieves high-fidelity statistical match against standard benchmarks (SEC EDGAR, World Bank, etc.).
3.  **Deterministic Integrity**: Every extracted record is tagged with SHA-256 checksums and immutable IDs for lineage tracking.
4.  **Multi-Tier Fallback**: Intelligent extraction pipeline that scales from Cloud APIs to local LLMs and regex heuristics.

## 🏗️ Documentation Layout

- [**User Manual**](user_manual.md): Installation, CLI reference, and BYOD configuration.
- [**Implementation Strategy**](implementation_strategy.md): Technical framework and provider pattern.
- [**Data Veracity Report**](data_veracity_report.md): Licensing compliance matrices and authoritative source manifests.
- [**Architecture Diagram**](architecture_diagram.md): Component-level technical breakdown.
- [**Industry Guides**](cross_sector/industrial_sectors.md):
    - **Anchors**: [Finance](finance/finance_guide.md), [Healthcare](healthcare/healthcare_guide.md), [Energy](energy/energy_guide.md), [Telecom](telecom/telecom_guide.md).
    - **Core Growth**: [Agriculture](agriculture/agriculture_guide.md), [Transportation](transportation/transportation_guide.md), [eCommerce](ecommerce/ecommerce_guide.md), [Unstructured](unstructured/unstructured_guide.md).
    - **Public Sector**: [Demographics](public_sector/demographics/demographics_guide.md), [Labor](public_sector/labor/labor_guide.md), [Environment](public_sector/environment/environment_guide.md), [Housing](public_sector/housing/housing_guide.md).
    - **Specialized**: [Education](education/education_guide.md), [Manufacturing](manufacturing/manufacturing_guide.md), [Media](media_and_entertainment/media_and_entertainment_guide.md), [Decision Support](cross_sector/industrial_sectors.md#16-decision-support).

---

### 🚀 Get Started
To initialize the engine and run your first extraction:
```bash
python dataproc_engine/cli/main.py extract --industry finance --limit 10
# Results saved to: industries/finance/datasets/finance_kb.jsonl
```

For detailed setup instructions, visit the [User Manual](user_manual.md).
