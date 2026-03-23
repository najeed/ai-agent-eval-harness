# 📦 Distribution Manifest (Hardened)

This manifest defines the distribution policy for the 16-sector dataset fleet. To ensure Apache 2.0 compatibility, restricted and NC-SA data is never bundled; instead, the engine provides **Logic-Only** synthesis paths.

---

## 🏗️ Bundled Datasets (Embedded)
*Safe for immediate redistribution. No raw PII or restricted records. Verified Statistical Parity.*

| Sector | Dataset Label | License | File Path |
| :--- | :--- | :--- | :--- |
| **Finance** | SEC Fundamentals | Public Domain | `industries/finance/datasets/synthetic_parity.jsonl` |
| **Demogs** | Population Trends | CC BY 4.0 | `industries/demographics/datasets/synthetic_parity.jsonl` |
| **Housing** | HUD Rental Trends | Public Domain¹ | `industries/housing/datasets/housing_kb.jsonl` |
| **Enviro** | NOAA Climatology | Public Domain | `industries/environment/datasets/noaa_climatology.jsonl` |
| **Enviro** | Copernicus Climate | CC BY 4.0² | `industries/environment/datasets/copernicus_climate.jsonl` |

¹ *HUD Fair Market Rents are U.S. Gov Public Domain. Attribution headers included as best practice.*
² *Mandatory attribution embedded: "Generated using Copernicus Climate Change Service information 2026."*

---

## 🔒 Restricted Datasets (Generator-Only)
*Redistribution prohibited. Run the local generator to produce your own "Statistical Twin". Statistical parameters are validated for first and second moment parity against benchmark sources.*

| Sector | Benchmark Description | Status | Restriction Type | Generator |
| :--- | :--- | :--- | :--- | :--- |
| **Healthcare** | Standard Clinical Repository | 🔒 Restricted | DUA / Credentialed | `clinical_generator.py` |
| **Energy** | Global Energy Standard | 🔒 Restricted | DUA / Restricted | `energy_generator.py` |
| **Manufacturing** | Industrial Benchmarking | 🔒 Restricted | DUA / Restricted | `industrial_generator.py` |
| **Retail** | E-Commerce Parity | 🔒 Restricted | **NC-SA 4.0**³ | `olist_generator.py` |
| **Agriculture** | Global Agri-Stats | 🔒 Restricted | **NC-SA 3.0**³ | `faostat_generator.py` |
| **Media** | Creative Metadata (IMDb) | 🔒 Restricted | **Non-Commercial**⁴ | `imdb_generator.py` |
| **Telecom** | Network Performance | 🔒 Restricted | **NC-SA 4.0**³ | `ookla_generator.py` |

³ **NC-SA Distinction**: These datasets are restricted by Copyright/ShareAlike. Synthetic outputs may inherit Non-Commercial restrictions.
⁴ **IMDb Policy**: Non-Commercial by ToS. No "ShareAlike" clause; derivative restriction analysis differs from CC BY-NC-SA sources.

---

## 🌐 Live Datasets (API / URL)
| Sector | Data Provider | Method | License |
| :--- | :--- | :---: | :--- |
| **Finance** | FRED | REST API | Upstream-dependent |
| **Agri-Tech** | USDA NASS | Quick Stats API | Public Domain |
| **Housing** | Zillow Research | Download | Non-Commercial⁵ |
| **Telecom** | FCC | Geospatial | Public Domain |
| **Labor** | ILOSTAT | REST API | CC BY / Restricted |
| **Labor** | Bureau of Labor Statistics (BLS) | Series API | Public Domain |

⁵ *Zillow Research data is for personal/academic use only. Commercial redistribution of bulk data is prohibited.*

---

## 🏛️ Comprehensive Registry (Citations)
| Industry | Primary Source / Citation URL | Format | License |
| :--- | :--- | :---: | :--- |
| **Finance** | [SEC EDGAR (Fundamentals)](https://www.sec.gov/edgar/searchedgar/companysearch.html) | XBRL/CSV | Public Domain |
| **Finance** | [FRED (Federal Reserve Economic Data)](https://fred.stlouisfed.org/) | API/CSV | Public Domain |
| **Environment** | [NOAA Climate Data Online](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily) | API/CSV | Public Domain |
| **Environment** | [Copernicus Climate Change Service](https://climate.copernicus.eu/data) | GRIB/NetCDF | CC BY 4.0² |
| **Healthcare** | [CMS Hospital General Information](https://data.cms.gov/provider-data/dataset/x7fx-mvoc) | CSV/API | Public Domain |
| **Healthcare** | [WHO Global Health Observatory](https://www.who.int/data/gho) | API/CSV | CC BY 4.0 |
| **Labor** | [U.S. Bureau of Labor Statistics (BLS)](https://www.bls.gov/data/) | API/CSV | Public Domain |
| **Labor** | [ILOSTAT (International Labour Organization)](https://ilostat.ilo.org/data/) | REST API | CC BY 4.0 |
| **Agriculture** | [FAOStat (Food and Agriculture Organization)](https://www.fao.org/faostat/en/#data) | CSV/API | CC BY-NC-SA 3.0 |
| **Agriculture** | [USDA NASS (Quick Stats)](https://quickstats.nass.usda.gov/) | CSV/API | Public Domain |
| **Commerce** | [Marketplace Parity Repository (Olist)](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | CSV | CC BY-NC-SA 4.0 |
| **Housing** | [HUD User (Fair Market Rents)](https://www.huduser.gov/portal/datasets/fmr.html) | CSV | Public Domain¹ |
| **Housing** | [Zillow Research (Economic Data)](https://www.zillow.com/research/data/) | CSV | Non-Commercial |
| **Media** | [IMDb Dataset Interface](https://www.imdb.com/interfaces/) | TSV | Non-Commercial |
| **Telecom** | [Ookla Open Data (Speedtest Intelligence)](https://www.ookla.com/ookla-for-good/open-data) | Parquet | CC BY-NC-SA 4.0 |
| **Telecom** | [FCC Fixed Broadband Deployment](https://www.fcc.gov/economics-analytics/broadband-insights-data/fixed-broadband-deployment-data) | CSV/API | Public Domain |
| **Manufact.** | [U.S. Census Bureau (ASM)](https://www.census.gov/programs-surveys/asm.html) | CSV/API | Public Domain |

*Full registry and veracity diagnostics available in the [Data Veracity & Provenance Report](data_veracity_report.md).*

---

## 🧪 Local Synthesis Guide
To generate a compliant parity dataset, use the dedicated scripts in the `generators/` directory. These scripts enforce the required compliance wrappers and inject legally defensible provenance metadata.

1. **Clinical**: `python industries/healthcare/generators/clinical_generator.py`
2. **Energy**: `python industries/energy/generators/energy_generator.py`
3. **Industrial**: `python industries/manufacturing/generators/industrial_generator.py`
4. **Olist**: `python industries/retail/generators/olist_generator.py`
5. **FAOStat**: `python industries/agriculture/generators/faostat_generator.py`
6. **IMDb**: `python industries/media_entertainment/generators/imdb_generator.py`
7. **Ookla**: `python industries/telecom/generators/ookla_generator.py`

---

## ⚖️ Terms of Use - Data & APIs
By using this harness, you agree to adhere to the terms of the respective data providers.
- **RESTRICTED Sources**: You must have a valid DUA or credentialing agreement with the relevant data provider to use raw restricted data locally.
- **NC-SA Sources**: You agree not to use synthetic outputs for commercial competition or redistribution where prohibited (e.g., Olist, Zillow).
- **Attribution**: You will maintain all embedded source headers in output artifacts.

---
*Last Updated: 2026-03-24 (Hardened)* ⚖️🛡️🏁
