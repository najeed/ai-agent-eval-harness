# dataproc-engine User Manual

Welcome to the **dataproc-engine**, a modular and extensible framework for generating high-quality industrial datasets for AI agent evaluation. This manual provides an end-to-end guide for setting up, configuring, and executing the data extraction and transformation pipeline.

For a technical breakdown of how the engine processes data, see the [Algorithm Overview](algorithm_overview.md).

---

## 🚀 1. Installation & Setup

### Prerequisites
- Python 3.9+
- Pip or Poetry

### Setup Steps
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/najeed/ai-agent-eval-harness.git
   cd ai-agent-eval-harness
   ```
2. **Install Dependencies**:
   ```bash
   pip install -e .
   ```
   *Note: This installs the core `dataproc-engine` and the `dataproc-cli` utility.*

---

## 🛠️ 2. CLI Usage Reference

The primary interface is the `dataproc-cli`.

### Basic Command Structure
```bash
python dataproc_engine/cli/main.py extract --industry [INDUSTRY] [FLAGS]
```

### Core Flags
| Flag | Description | Example |
| :--- | :--- | :--- |
| `--industry` | Target industrial sector (8 sectors available). | `finance`, `healthcare` |
| `--limit` | Maximum number of records to process. | `--limit 100` |
| `--schema-type` | Specific gold-standard schema configuration. | `mimic_iv`, `sec_edgar` |
| `--input-uri` | Local path or Web URL to user-provided data (BYOD override). | `--input-uri https://example.com/data.csv` |
| `--overwrite` | Bypasses the conflict prompt for existing output. | `--overwrite` |

---

## 🌐 3. Industrial Data Sectors

The engine supports 14 schema configurations across 8 sectors.

| Sector | Default Source | Gold Standard Schema | Status |
| :--- | :--- | :--- | :--- |
| **Finance** | SEC EDGAR | `sec_edgar`, `credit_risk` | Live / Sim |
| **Healthcare** | CMS Ratings | `mimic_iv` (Modern), `mimic_iii` | Live / Sim |
| **Telecom** | FCC Availability | `ookla` (Speed Tiles) | Live / Sim |
| **Energy** | US EIA | `iea_global` (Balances) | Live / Sim |
| **Ecommerce** | Amazon (Mock) | `olist` / `uci` | Live / Local |
| **Agriculture**| USDA NASS | `standard` | Live |
| **Transport** | US DOT/GTFS | `standard` | Live |
| **Unstructured**| Doc Search | `unstructured` | Live |

---

## 🛡️ 4. Gold Standards & BYOD (Bring Your Own Data)

### Compliance-First Architecture
For restricted datasets (CC BY-NC-SA 4.0, PhysioNet, IEA), the engine defaults to **High-Fidelity Simulations** to ensure 100% Apache 2.0 compliance for redistribution.

### Unlocking Live Processing
To use actual commercial/restricted benchmarks, follow these steps:
1. **Apply for Access**: Use the links in the [Data Veracity Report](data_veracity_report.md) to download the data.
2. **Execution**:
   ```bash
   python dataproc_engine/cli/main.py extract --industry healthcare --schema-type mimic_iv --input-uri ./my_mimic_data/labevents.csv
   ```

---

## 🔑 5. Configuration & Secrets

Configuration is managed via `config.json` or Environment Variables.

### API Keys
| Service | Environment Variable | Config Key |
| :--- | :--- | :--- |
| **EIA** | `EIA_API_KEY` | `eia_api_key` |
| **FRED** | `FRED_API_KEY` | `fred_api_key` |
| **Ookla** | `OOKLA_API_KEY` | `ookla_api_key` |

---

## 📊 6. Output & Veracity
Every record produced by the engine adheres to the `StandardSchema`, including:
- **Deterministic ID**: Hash-based records for cross-dataset linking.
- **SHA-256 Integrity**: Every record includes a checksum of its normalized data.
- **Provenance**: Lineage back to the source URL or local file path.

---

---

## 🔄 8. Rotational Dataset Archiving
To prevent accidental data loss (especially when local changes are overwritten by CI/CD triggers), the engine implements a **Rolling Backup Policy**:

*   **Automatic Archiving**: When a file conflict occurs (even with `--overwrite`), the engine renames the existing file to `<filename>.<timestamp>.bak`.
*   **Rotation**: By default, the engine keeps the **last 5 backups** and automatically prunes older ones.
*   **Customization**: Use the `--max-backups` flag to control the rotation length:
    ```bash
    # Keep the last 10 versions
    python dataproc_engine/cli/main.py extract --industry finance --max-backups 10
    ```

---

## ⚖️ 9. Licensing & Attribution
- **Code**: Apache 2.0.
- **Shipped Data**: Synthetic boilerplate only (Safe for redistribution).
- **External Data**: Must adhere to respective licenses (CC BY, PhysioNet, IEA).

For detailed licensing guidance, see the [Data Veracity Report](data_veracity_report.md).
