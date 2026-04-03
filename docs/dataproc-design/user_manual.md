# dataproc-engine User Manual

Welcome to the **dataproc-engine**, a modular and extensible framework for generating high-quality industrial datasets for AI agent evaluation. This manual provides an end-to-end guide for setting up, configuring, and### 📚 Supporting Documentation
- [Implementation Strategy](implementation_strategy.md)
- [Architecture Diagram](architecture_diagram.md)
- [Data Veracity Report](data_veracity_report.md)
- [Algorithm Overview](cross_sector/algorithm_overview.md)
- [Target Schema](scenario_schema.md)

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
| `--industry` | Target industrial sector (16 sectors available). | `finance`, `healthcare`, `media_and_entertainment` |
| `--limit` | Maximum number of records to generate/process. | `--limit 100` |
| `--format` | Output dataset format (`jsonl` or `csv`). | `--format csv` |
| `--source` | Data acquisition mode (`api` for live or `file` for local ingestion). | `--source file` |
| `--input-uri` | Local path or Web URL for `file` source ingestion (BYOD override). | `--input-uri https://example.com/data.csv` |
| `--llm-strategy` | Transformation execution strategy (`auto`, `cloud`, `ollama`, `heuristic`, `mock`). | `--llm-strategy ollama` |
| `--model` | Specific model identifier for the LLM provider. | `--model gemini-1.5-pro` |
| `--overwrite` | Force-overwrite existing output files (also triggers safety backup). | `--overwrite` |
| `--max-backups` | Maximum number of rolling rotational backups to maintain. | `--max-backups 10` |
| `--allow-simulation`| V2.0-STABLE: explicit toggle for high-fidelity simulation fallbacks. | `--allow-simulation` |
| `--schema-type` | Specific industry gold-standard schema configuration variant. | `clinical`, `sec_edgar`, `policy_risk` |

---

## 🌐 3. Industrial Data Sectors

The engine supports **16 standard industrial sectors** with specialized gold-standard schemas. Use the strings below for the `--industry` flag.

| Sector Group | Industry ID (`--industry`) | Primary Schema Types (`--schema-type`) | Gold Source |
| :--- | :--- | :--- | :--- |
| **Finance** | `finance` | `sec_edgar`, `credit_risk`, `world_bank` | SEC, FRED |
| **Energy** | `energy` | `eia`, `energy_balances`, `standard` | EIA, Energy Provider Agency |
| **Healthcare** | `healthcare` | `cms`, `clinical`, `standard` | CMS, WHO |
| **Telecom** | `telecom` | `fcc`, `ookla`, `standard` | FCC, Ookla |
| **Public Sector** | `demographics` | `standard`, `global_population` | World Bank |
| **Public Sector** | `labor` | `standard`, `ilo_employment` | ILO, BLS |
| **Public Sector** | `housing` | `standard`, `hud_market` | HUD |
| **Public Sector** | `environment` | `standard`, `climate_noaa` | NOAA |
| **Academic** | `education` | `standard`, `nces_stats` | NCES, UNESCO|
| **Industrial** | `manufacturing` | `standard`, `industrial_stats` | Industrial Statistics Agency |
| **Commercial** | `agriculture` | `standard`, `usda_crops` | USDA |
| **Commercial** | `ecommerce` | `olist`, `uci_retail`, `standard` | Olist, UCI |
| **Logistics** | `transportation` | `standard`, `bts_ontime` | BTB, Eurostat|
| **Foundational**| `media_and_entertainment`| `standard`, `imdb_cultural` | IMDb |
| **Foundational**| `decision_support` | `standard`, `signal_linking` | Correlator |
| **Foundational**| `unstructured` | `standard`, `llm_scraper` | Scrapers |

### Full Industry List & Schema Types
- [Finance Guide](finance/finance_guide.md)
- [Healthcare Guide](healthcare/healthcare_guide.md)
- [Energy Guide](energy/energy_guide.md)
- [Telecom Guide](telecom/telecom_guide.md)
- [Ecommerce Guide](ecommerce/ecommerce_guide.md)
- [Agriculture Guide](agriculture/agriculture_guide.md)
- [Transportation Guide](transportation/transportation_guide.md)
- [Manufacturing Guide](manufacturing/manufacturing_guide.md)
- [Demographics Guide](public_sector/demographics/demographics_guide.md)
- [Labor Guide](public_sector/labor/labor_guide.md)
- [Environment Guide](public_sector/environment/environment_guide.md)
- [Education Guide](education/education_guide.md)
- [Housing Guide](public_sector/housing/housing_guide.md)
- [Media & Entertainment Guide](media_and_entertainment/media_and_entertainment_guide.md)
- [Decision Support Guide](cross_sector/decision_support_guide.md)
- [Unstructured Guide](cross_sector/unstructured_guide.md)

---

## 🛡️ 4. Gold Standards & BYOD (Bring Your Own Data)

### Compliance-First Architecture (Zero-Input Simulation)
For all 16 sectors, the engine implements a mission-critical **Zero-Input Fallback**. If no `--input-uri` is provided and API keys are absent, the engine defaults to **High-Fidelity Simulations**. 
- **Parity Guarantee**: 100% of the industrial suite will produce `StandardSchema` records even in air-gapped or mock environments.
- **Contract**: Every simulation is industry-aware (e.g., Olist/UCI for Ecommerce, USDA/FAOStat for Agriculture).

### Unlocking Live Processing
To use actual commercial/restricted benchmarks, follow these steps:
1. **Apply for Access**: Use the links in the [Data Veracity Report](data_veracity_report.md) to download the data.
2. **Execution**:
   ```bash
   python dataproc_engine/cli/main.py extract --industry healthcare --source file --input-uri ./my_clinical_data/labevents.csv --schema-type clinical
   ```

### 📂 Default Output Layout
If `--target-dir` is not specified, the engine automatically resolves the path to ensure organizational parity:
*   **Path**: `industries/{industry}/datasets/`
*   **Knowledge Base (JSONL)**: `{industry}_kb.jsonl`
*   **Records (CSV)**: `{industry}_records.csv`

### 🚀 Examples
1.  **Extract Finance Data (Default)**:
    ```bash
    python dataproc_engine/cli/main.py extract --industry finance
    # Saved to: industries/finance/datasets/finance_kb.jsonl
    ```

---

## 🔑 5. Configuration & Secrets

Configuration is managed via `config.json` or Environment Variables.

### API Keys & Secrets
| Service | Environment Variable | Config Key | Industry |
| :--- | :--- | :--- | :--- |
| **EIA** | `EIA_API_KEY` | `eia_api_key` | Energy |
| **FRED** | `FRED_API_KEY` | `fred_api_key` | Finance |
| **NCES** | `NCES_API_KEY` | `nces_api_key` | Education |
| **ILO** | `ILO_API_KEY` | `ilo_api_key` | Labor |
| **Industrial Statistics Agency** | `Industrial Statistics Agency_API_KEY` | `Industrial Statistics Agency_api_key` | Manufacturing |
| **Copernicus**| `CDS_API_KEY` | `cds_api_key` | Environment |
| **Ookla** | `OOKLA_API_KEY` | `ookla_api_key` | Telecom |
| **Spotify** | `SPOTIFY_CLIENT_ID` | `spotify_client_id`| Media |
| **Backup Retention Policy** | `DATAPROC_MAX_BACKUPS` | N/A | CLI Global |

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
*   **Customization**: Use the `--max-backups` flag or set the `DATAPROC_MAX_BACKUPS` environment variable:
    ```bash
    # Keep the last 10 versions via CLI
    python dataproc_engine/cli/main.py extract --industry finance --max-backups 10

    # Keep the last 10 versions via Env Var (Windows)
    $env:DATAPROC_MAX_BACKUPS="10"
    ```

---

## ⚖️ 9. Licensing & Attribution
- **Code**: Apache 2.0.
- **Shipped Data**: Synthetic boilerplate only (Safe for redistribution).
- **External Data**: Must adhere to respective licenses (CC BY, Restricted Clinical Repository, Energy Provider Agency).

For detailed licensing guidance, see the [Data Veracity Report](data_veracity_report.md).
