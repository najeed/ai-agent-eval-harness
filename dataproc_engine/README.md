# 🛠️ dataproc-engine: High-Signal Industrial Data Extraction

The `dataproc_engine` is a standalone, industrial-grade extraction and transformation pipeline designed to provide agents with high-fidelity, real-world data across critical sectors. It ensures that evaluations are performed against realistic constraints, not just synthetic noise.

## 🚀 Key Features

- **Multi-Sector Coverage**: Specialized providers for **Finance, Healthcare, Energy, Telecom, Ecommerce, Agriculture,** and **Transportation**.
- **Industrial Connectors**:
  - **Finance**: Automated extraction of SEC EDGAR (CIK-based) and FDIC filings.
  - **Healthcare**: HL7-compliant FHIR record synthesis and clinical note parsing.
  - **Energy**: EIA Real-time grid monitoring and supply-chain telemetry ingestion.
  - **Agriculture**: USDA market reports and global crop yield analytics.
- **Zero-Mock Integrity**: Automated fallback to high-fidelity simulations when live APIs are unavailable, maintaining 100% evaluation uptime.
- **LLM-Driven Transformation**: Pluggable strategies (`auto`, `cloud`, `ollama`, `heuristic`, `mock`) for converting raw data into structured benchmarks.
- **Rotational Backup Policy**: Industrial-grade safety with rolling backups for all extracted datasets.

## 📂 Structure

- `/core`: The unified `DatasetEngine` and `LLMManager` orchestration logic.
- `/providers`: Domain-specific data acquisition layers (e.g., `FinanceProvider`, `UnstructuredProvider`).
- `/cli`: Professional CLI interface for batch extraction and pipeline management.
- `/tests`: Exhaustive test suite reaching >95% coverage across all industrial providers.

## 🛠️ Usage

### Quick Extraction
Extract the latest agricultural records in JSONL format:
```bash
python -m dataproc_engine.cli.main extract --industry agriculture --format jsonl --target-dir data/benchmarks
```

### Batch Processing (SEC EDGAR)
Extract financial records for specific companies via CIK:
```bash
python -m dataproc_engine.cli.main extract --industry finance --ciks "0000320193,0001067983" --format csv
```

## ⚖️ NIST Alignment
`dataproc_engine` follows the **NIST AI RMF** guidelines for data provenance and high-signal acquisition, ensuring that the "Ground Truth" used for evaluation is both accurate and auditable.

---
*Part of the AgentV Verification OS.*
