# Data Veracity Report ⚖️

This report documents the primary data sources, gold-standard benchmarks, and veracity standards applied across the 8 industrial sectors supported by the `dataproc-engine`.

## 🛡️ Licensing & Redistribution Compliance

The `dataproc-engine` is an Apache 2.0 licensed project. To maintain compliance, we adhere to a **Zero-Redistribution Policy** for restricted datasets.

### Dataset Licensing Compliance Matrix

| Dataset License / Source | Safe to Embed in Apache 2.0 Repo? | Link-Provided (User Download)? | Conditions |
| :--- | :--- | :--- | :--- |
| **Public Domain** (SEC, USDA, BTS, CMS, FCC, EIA) | ✅ Yes | ✅ Yes | Free use; attribution recommended. |
| **CC BY 4.0** (UCI Credit/Retail, some GTFS) | ✅ Yes | ✅ Yes | Attribution required; commercial use allowed. |
| **CC BY-NC-SA 4.0** (Olist, Ookla) | ❌ No | ✅ Yes | Non-commercial + share-alike conflict with Apache 2.0. |
| **GTFS Specification** (Apache 2.0) | ✅ Yes | ✅ Yes | Specification is Apache 2.0; **feeds vary by agency**. |
| **PhysioNet Restricted** (MIMIC-III/IV) | ❌ No | ✅ Yes | Credentialed access only; redistribution prohibited. |
| **IEA Terms & Conditions** (Energy) | ❌ No | ✅ Yes | Paywalled/gated; redistribution prohibited. |

> [!TIP]
> **Best Practice**: Embed only Public Domain and CC BY 4.0 datasets in the repo. Link to CC BY-NC-SA, PhysioNet, and IEA datasets with clear instructions for users to obtain them under their own credentials or API keys.

### ⚠️ Licensing Nuances
- **FRED (Federal Reserve)**: While broadly open, it is governed by **Terms of Use** (requiring attribution and prohibiting misrepresentation), not strictly Public Domain.
- **GTFS Feeds**: The Specification is Apache 2.0, but actual transit feeds vary by agency. Always check the individual feed license before redistribution.
- **CMS Data**: Public domain, but official attribution is best practice for data veracity audit trails.

> [!IMPORTANT]
> **Shipped Data**: The `.csv` files provided in the `industries/` directory are **Synthetic Templates** designed for boilerplate testing. They do NOT contain restricted real-world records.

---

## 🏗️ Data Onboarding (BYOD)

To unlock the full "Gold Standard" evaluation, download the following datasets and provide the path via the `--input-uri` flag or in your provider configuration. Please review the respective licensing restrictions for redistribution.

| Industry | Benchmark | Download Link | License |
| :--- | :--- | :--- | :--- |
| **Finance** | UCI Credit Card | [UCI ML Repository](https://archive.ics.uci.edu/ml/datasets/default+of+credit+card+clients) | CC BY 4.0 |
| **Healthcare** | MIMIC-IV | [PhysioNet MIMIC-IV](https://physionet.org/content/mimiciv/) | PhysioNet RL |
| **Telecom** | Ookla Speedtest | [GitHub (teamookla)](https://github.com/teamookla/ookla-open-data) | CC BY-NC-SA 4.0 |
| **Energy** | IEA Balances | [IEA Statistics](https://www.iea.org/data-and-statistics/data-products?filter=energy-balances) | IEA Terms |
| **Retail** | Olist Ecommerce | [Kaggle Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | CC BY-NC-SA 4.0 |

---

## 1. Finance
- **Securities and Exchange Commission (SEC) EDGAR**:
    - *Usage*: Company fundamentals, XBRL facts.
    - *Status*: **LIVE** (Public API).
    - *License*: **Public Domain**.
- **Federal Reserve Economic Data (FRED)**:
    - *Usage*: Macroeconomic indicators.
    - *Status*: **LIVE** (Public API).
    - *License*: **Terms of Use (Open)**.
- **UCI Default of Credit Card Clients**:
    - *Usage*: Credit risk behavior.
    - *Status*: **SIMULATED** (Shipped) / **BYOD** (Unlocked).
    - *License*: **CC BY 4.0**.

## 2. E-Commerce
- **Olist Brazilian E-Commerce Dataset**:
    - *Usage*: Relational modeling of orders/payments.
    - *Status*: **SYNTHETIC TEMPLATE** (Shipped) / **BYOD** (Unlocked).
    - *License*: **CC BY-NC-SA 4.0** (Non-Commercial).
    - *Implications*:
        - ❌ **Apache 2.0 Conflict**: Non-Commercial/Share-Alike terms prevent embedding in this repo.
        - ✅ **External Linking**: Users must download directly from Kaggle.
        - ✅ **Research Use**: Permitted under CC BY-NC-SA terms.
    - *Unlock*: Provide `input_uri` to Olist CSV files.
- **UCI Online Retail Dataset**:
    - *Usage*: Transactional retail analysis.
    - *Source*: [UCI Online Retail](https://archive.ics.uci.edu/ml/datasets/online+retail)
    - *License*: **CC BY 4.0**.

## 3. Agriculture
- **USDA NASS Quick Stats**:
    - *Usage*: Crop yields and commodity pricing.
    - *Status*: **LIVE / LOCAL TEMPLATE**.
    - *License*: **Public Domain**.

## 4. Transportation
- **U.S. Bureau of Transportation Statistics (BTS)**:
    - *Usage*: Airline on-time performance.
    - *Status*: **SYNTHETIC TEMPLATE** (Shipped) / **BYOD** (Unlocked).
    - *License*: **Public Domain**.

## 5. Healthcare
- **CMS Hospital General Information**:
    - *Usage*: Quality ratings and patient experience.
    - *Status*: **LIVE / LOCAL TEMPLATE**.
    - *License*: **Public Domain**.
- **MIMIC-IV Clinical Database** (Recommended):
    - *Usage*: Modern, modular ICU clinical data (2008-2019). Supports ICD-10 and granular patient trajectories.
    - *Status*: **SIMULATED** (Shipped) / **BYOD** (Unlocked).
    - *License*: **PhysioNet Credentialed Data Use Agreement (DUA)**.
    - *Implications*:
        - ❌ **Not Public Domain**: Access requires credentialing (Human subjects training + approval).
        - ❌ **Redistribution Prohibited**: Cannot be included in Apache 2.0 or commercial products.
        - ✅ **Internal Use Permitted**: Research and testing allowed once credentialed.
    - *Unlock*: Provide `input_uri` to restricted-access CSVs (e.g., `hosp/labevents.csv.gz`).
    - *Download*: [PhysioNet MIMIC-IV](https://physionet.org/content/mimiciv/)
- **MIMIC-III Clinical Database** (Legacy):
    - *Usage*: Older clinical research data (2001-2012). Primarily ICD-9 based.
    - *Status*: **SIMULATED** (Shipped) / **BYOD** (Unlocked).
    - *License*: **PhysioNet Credentialed DUA**.

## 6. Telecom
- **FCC Broadband Data Collection (BDC)**:
    - *Usage*: Connectivity maps and technology availability.
    - *Status*: **LIVE / LOCAL TEMPLATE**.
    - *License*: **Public Domain**.
- **Ookla Open Data**:
    - *Usage*: Global network performance benchmarking.
    - *Status*: **SIMULATED** (Shipped) / **BYOD** (Unlocked).
    - *License*: **CC BY-NC-SA 4.0**.
    - *Implications*:
        - ❌ **Commercial Restriction**: License prohibits commercial redistribution.
        - ❌ **Embedding Prohibited**: Must be kept external to Apache 2.0 projects.
    - *Unlock*: Provide `ookla_api_key` or `input_uri` to performance tiles.
    - *Download*: [Ookla Open Data GitHub](https://github.com/teamookla/ookla-open-data)

## 7. Energy
- **U.S. Energy Information Administration (EIA)**:
    - *Usage*: Energy production and pricing.
    - *Status*: **LIVE** (Public API) / **LOCAL TEMPLATE**.
    - *License*: **Public Domain**.
- **International Energy Agency (IEA)**:
    - *Usage*: Global energy balances.
    - *Status*: **SIMULATED** (Shipped) / **BYOD** (Unlocked).
    - *License*: **IEA Terms and Conditions**.
    - *Implications*:
        - ❌ **Paywalled/Gated**: Requires purchase or authorized registration.
        - ❌ **No Redistribution**: IEA strictly prohibits repackaging data.
        - ✅ **Simulation Allowed**: Harness provides high-fidelity schema for logic testing.
    - *Unlock*: Provide `iea_api_key` or `input_uri` to licensed balance sheets.

---

## 🛡️ Provenance & Dataset Safety

To ensure the integrity of the evaluation cycle, the `dataproc-engine` implements two primary safety layers:

### 1. Rotational Dataset Archiving
When executing the `extract` command, existing datasets are never silently overwritten. Instead, the engine performs a **microsecond-precision rotation**:
- Existing files are renamed to `<filename>.<timestamp>.bak`.
- A rolling history of up to 5 backups (default) is maintained.
- Users can customize history depth via `--max-backups`.

### 2. Universal Remote Acquisition
The engine supports direct ingestion from remote HTTPS/S URLs. To ensure veracity during transit:
- **Resilient Fetching**: Automatic exponential backoff and circuit breaker logic protect against transient network failures.
- **Deterministic Checksums**: All ingested artifacts are tagged with a SHA-256 hash of their raw content, ensuring that "Gold Standard" sources remain untampered.

---
*Last Updated: 2026-03-23*
