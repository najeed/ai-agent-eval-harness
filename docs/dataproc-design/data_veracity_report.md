# Data Veracity & Provenance Report (Hardened)

## Licensing & Synthesis Compliance Matrix ⚖️

To ensure Apache 2.0 compatibility across the 16-sector fleet, the engine adheres to the following distribution matrix:

| Source Category | Examples | Safe to Embed? | Generator Mode | Licensing Conditions |
| :--- | :--- | :---: | :--- | :--- |
| **Public Domain** | SEC, Census, NOAA, HUD, CMS | ✅ Yes | **Moment Parity** | Derived/Synthetic twins allowed. |
| **CC BY / CC0** | World Bank, WHO, UNESCO | ✅ Yes | **Moment Parity** | Attribution required (CC BY). |
| **NC-SA / NC** | Olist, Ookla, Zillow, IMDb | ❌ No | **Logic Only** | NC/SA prevents redistribution. |
| **Restricted (DUA)** | Clinical Repository, Industrial Stats | ❌ No | **Logic Only** | Contractual gates (Credentialed). |

### Parity Generation Principles (Conservative Stance)
1. **Conservative Default**: If a license is NC (Non-Commercial) or Restricted (DUA), the engine distributes **Logic Only**. No synthetic approximations are embedded in the core repo for these sources.
2. **Provenance Audit**: All synthetic data includes a defensible audit trail link back to the permissive original.
3. **Parameter Integrity**: Parameters for restricted generators are sourced exclusively from public literature (e.g., Merck Manuals, Energy Statistics Yearbooks), not from gated raw data.
4. **License Contamination (NC-SA)**: Because CC BY-NC-SA 4.0 carries a "ShareAlike" clause, synthetic outputs generated from these sources may inherit Non-Commercial restrictions. To protect the Apache 2.0 core, these generators are isolated from the embedded package.

### ⚠️ Licensing Nuances
- **FRED (Federal Reserve)**: Licensing is **upstream-dependent**. Series sourced from the Federal Reserve are Public Domain; others (BIS, ECB) carry their own terms.
- **Copernicus**: Licensed under the Copernicus Data Information and Access Services license (CC BY 4.0 equivalent). Mandatory attribution: "Generated using Copernicus Climate Change Service information 2026."
- **HUD User**: Fair Market Rents (FMR) data is U.S. Government Public Domain. Attribution is best practice for data veracity audit trails.
- **Zillow Research**: Personal/Academic use only. Prohibits bulk redistribution or commercial derivative services per [Developer Terms](https://www.zillowgroup.com/developers/terms/).
- **IMDb**: Non-Commercial by ToS. No "ShareAlike" clause; derivative restriction analysis differs from CC BY-NC-SA sources.

---

## 🏗️ Data Onboarding (BYOD)

To unlock the full "Gold Standard" evaluation, download the following datasets and provide the path via the `--input-uri` flag. Please review the respective licensing restrictions for use and redistribution.

| Industry | Target Benchmark | Download Link | License |
| :--- | :--- | :--- | :--- |
| **Finance**| UCI Credit Card | [UCI ML Repository](https://archive.ics.uci.edu/ml/datasets/default+of+credit+card+clients) | CC BY 4.0 |
| **Healthcare**| Clinical Data Example | [Restricted Access](https://physionet.org/content/mimiciv/) | Restricted (Credentialed) |
| **Manufacturing**| Industrial Benchmarking | [Production Statistics](https://stat.unido.org/) | Restricted |
| **Energy**| Global Energy Standard | [Global Statistics](https://www.iea.org/data-and-statistics) | Restricted |
| **Retail**| E-Commerce Parity | [Transaction Logs](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | CC BY-NC-SA 4.0 |
| **Agriculture**| Global Agri-Stats | [FAOStat](https://www.fao.org/faostat/) | CC BY-NC-SA 3.0 |
| **Media** | Creative Metadata | [IMDb Datasets](https://datasets.imdbws.com/) | Non-Commercial |

---

## 🛡️ Sector Diagnostics

## 1. Finance
- **SEC EDGAR**: Public Domain fundamentals. Synthetic templates embedded.
- **FRED**: Open (Attribution required) macro data. Live API integration.

## 2. Housing
- **HUD User**: Public Domain rental trends. Synthetic parity embedded.
- **Zillow Research**: Non-Commercial macro housing metrics. Live download required.

## 3. Environment
- **NOAA**: Public Domain station data. Climatology synthetic records embedded.
- **Copernicus**: CC BY 4.0 monitoring data. Embedded with mandatory attribution.

## 4. Manufacturing
- **Industrial Stats**: Restricted benchmarking. **Logic-only** parity synthesis.
- **Census ASM**: Public Domain manufacturing aggregates. Synthetic templates available.

## 5. Healthcare
- **CMS**: [Hospital General Info](https://data.cms.gov/)
    - *Usage*: Quality outcomes and provider metadata. **LIVE** (Public Domain).
- **WHO GHO**: [Global Health Observatory](https://www.who.int/data/gho)
    - *Usage*: Global health trends. **LIVE** (CC BY 4.0).
- **Clinical Database**:
    - *Usage*: Intensive care records. **BYOD / SIMULATED** (Restricted).

---

## 6. Education
- **UNESCO (UIS)**: CC BY-SA 3.0 IGO. Global literacy and enrollment metrics. **LIVE/SIMULATED**.
- **NCES**: Public Domain. U.S. institutional data. **LIVE/SIMULATED**.

## 7. Energy
- **EIA**: Public Domain. U.S. sectoral balances. **LIVE** (API required).
- **OPSD**: CC BY 4.0. European grid time-series. **Logic-only** synthesis templates.

## 8. Transport
- **Eurostat**: Open Data. Regional logistics statistics. **LIVE**.
- **OSM**: ODbL. Geospatial node/way parity. **Logic-only** synth through Overpass API.

## 9. Unstructured
- **Common Crawl**: Terms of Use. WARC-based general knowledge. **Scrubbed** local ingest only.

---

## 🏛️ Comprehensive Registry (Citations)

| Industry | Primary Source / Citation URL | Format | License |
| :--- | :--- | :---: | :--- |
| **Finance** | [SEC EDGAR (Fundamentals)](https://www.sec.gov/edgar/searchedgar/companysearch.html) | XBRL/CSV | Public Domain |
| **Finance** | [FRED (Federal Reserve Economic Data)](https://fred.stlouisfed.org/) | API/CSV | Public Domain |
| **Finance** | [World Bank Open Data](https://data.worldbank.org/) | API/CSV | CC BY 4.0 |
| **Environment** | [NOAA Climate Data Online](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily) | API/CSV | Public Domain |
| **Environment** | [Copernicus Climate Change Service](https://climate.copernicus.eu/data) | GRIB/NetCDF | CC BY 4.0 |
| **Healthcare** | [CMS Hospital General Information](https://data.cms.gov/provider-data/dataset/x7fx-mvoc) | CSV/API | Public Domain |
| **Healthcare** | [WHO Global Health Observatory](https://www.who.int/data/gho) | API/CSV | CC BY 4.0 |
| **Labor** | [U.S. Bureau of Labor Statistics (BLS)](https://www.bls.gov/data/) | API/CSV | Public Domain |
| **Labor** | [ILOSTAT (International Labour Organization)](https://ilostat.ilo.org/data/) | REST API | CC BY 4.0 |
| **Agriculture** | [FAOStat (Food and Agriculture Organization)](https://www.fao.org/faostat/en/#data) | CSV/API | CC BY-NC-SA 3.0 |
| **Agriculture** | [USDA NASS (Quick Stats)](https://quickstats.nass.usda.gov/) | CSV/API | Public Domain |
| **Commerce** | [Marketplace Parity Repository (Olist)](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) | CSV | CC BY-NC-SA 4.0 |
| **Housing** | [HUD User (Fair Market Rents)](https://www.huduser.gov/portal/datasets/fmr.html) | CSV | Public Domain |
| **Housing** | [Zillow Research (Economic Data)](https://www.zillow.com/research/data/) | CSV | Non-Commercial |
| **Media** | [IMDb Dataset Interface](https://www.imdb.com/interfaces/) | TSV | Non-Commercial |
| **Telecom** | [Ookla Open Data (Speedtest Intelligence)](https://www.ookla.com/ookla-for-good/open-data) | Parquet | CC BY-NC-SA 4.0 |
| **Telecom** | [ITU (International Telecommunication Union)](https://datahub.itu.int/) | API | CC BY-NC-SA 3.0 |
| **Telecom** | [FCC Fixed Broadband Deployment](https://www.fcc.gov/economics-analytics/broadband-insights-data/fixed-broadband-deployment-data) | CSV/API | Public Domain |
| **Manufact.** | [U.S. Census Bureau (ASM)](https://www.census.gov/programs-surveys/asm.html) | CSV/API | Public Domain |
| **Transport** | [Eurostat Database](https://ec.europa.eu/eurostat/data/database) | API/CSV | Open Data |
| **Transport** | [OpenStreetMap (OSM) Geography](https://www.openstreetmap.org/copyright) | PBF/XML | ODbL |
| **Energy** | [U.S. Energy Information Admin (EIA)](https://www.eia.gov/opendata/) | API/CSV | Public Domain |
| **Energy** | [Open Power System Data (OPSD)](https://open-power-system-data.org/) | CSV | CC BY 4.0 |
| **Education** | [UNESCO Institute for Statistics (UIS)](https://uis.unesco.org/) | API | CC BY-SA 3.0 |
| **Education** | [NCES (National Center for Education Statistics)](https://nces.ed.gov/) | API | Public Domain |
| **Unstructured**| [Common Crawl Datasets](https://commoncrawl.org/the-data/) | S3/WARC | CC TOU |


---
*Last Updated: 2026-03-31 (Hardened)* 
