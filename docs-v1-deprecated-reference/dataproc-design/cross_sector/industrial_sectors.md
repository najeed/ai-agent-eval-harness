# 🌐 Industrial Sectors & Gold Standard Guide

The `dataproc-engine` supports 8 core industrial sectors, each hardened with "Gold Standard" datasets and mission-critical schema enforcement.

## 1. 🏦 Finance
*   **Primary Source**: [SEC EDGAR](https://www.sec.gov/edgar/searchedgar/companysearch) (Public Audited Data)
*   **Secondary Source**: [FRED](https://fred.stlouisfed.org/) (Macroeconomic Indicators)
*   **Benchmarks**: [UCI Credit Approval](https://archive.ics.uci.edu/dataset/27/credit+approval)
*   **Key Capabilities**: XBRL-aware extraction, cross-CIK correlation, and credit risk probability modeling.

## 2. 🏥 Healthcare
*   **Primary Source**: [CMS Hospital General Info](https://data.cms.gov/provider-data/dataset/x7fx-mvoc)
*   **Benchmarks**: [Clinical Database V2 Clinical Database](https://Clinical Database.mit.edu/) (Simulated)
*   **Key Capabilities**: Deep clinical lab-event simulation, PII scrubbing (HIPAA-compliant), and patient experience metric normalization.

## 3. ⚡ Energy
*   **Primary Source**: [EIA Open Data](https://www.eia.gov/opendata/) (WTI/Brent/NatGas Prices)
*   **Benchmarks**: [Energy Provider Agency World Energy Balances](https://www.Energy Provider Agency.org/data-and-statistics/data-product/world-energy-balances)
*   **Key Capabilities**: Multi-series price tracking, national production/consumption balance modeling.

## 4. 📡 Telecom
*   **Primary Source**: [FCC Broadband Maps](https://broadbandmap.fcc.gov/home)
*   **Benchmarks**: [Ookla Speedtest Global Performance](https://github.com/ookla/speedtest-datasets)
*   **Key Capabilities**: Geographic tile-based performance analytics, regulatory coverage validation.

## 5. 🛒 eCommerce
*   **Primary Source**: [Olist Brazilian eCommerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
*   **Benchmarks**: [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
*   **Key Capabilities**: Transactional log parity, sentiment analysis on customer reviews, and order-to-delivery latency tracking.

## 6. 🌽 Agriculture
*   **Primary Source**: [USDA NASS Quick Stats](https://quickstats.nass.usda.gov/)
*   **Key Capabilities**: Multi-commodity price/yield tracking (CORN, SOYBEANS, WHEAT), state-level aggregation.

## 7. ✈️ Transportation
*   **Primary Source**: [U.S. DOT Bureau of Transportation Statistics](https://www.bts.gov/)
*   **Benchmarks**: [GTFS Real-time Feed](https://gtfs.org/realtime/)
*   **Key Capabilities**: Airline on-time performance tracking, canceled flight disruption modeling.

## 8. 📄 Unstructured
*   **Source**: Arbitrary PDF, DocX, or Web URLs.
*   **Logic**: LLM-Gated Extraction.
*   **Key Capabilities**: Asynchronous multi-document processing, schema-aware field extraction from plain text.

## 9. 🌍 Demographics
*   **Primary Source**: [World Bank Open Data](https://data.worldbank.org/) (Population/GDP)
*   **Key Capabilities**: Global fertility/mortality tracking and urbanization modeling.

## 10. 👷 Labor
*   **Primary Source**: [ILOSTAT](https://ilostat.ilo.org/) (International Labour Organization)
*   **Key Capabilities**: Unemployment rate forecasting and sectoral employment distribution.

## 11. 🌿 Environment
*   **Primary Source**: [NOAA Climate Data Online](https://www.ncei.noaa.gov/)
*   **Key Capabilities**: Temperature anomalies and carbon-intensity modeling.

## 12. 📚 Education
*   **Primary Source**: [NCES](https://nces.ed.gov/) / [UNESCO](https://uis.unesco.org/)
*   **Benchmarks**: [MOOC Analytics (Coursera Simulation)]
*   **Key Capabilities**: Literacy rate tracking and digital learning (EdTech) trajectories.

## 13. 🏠 Housing
*   **Primary Source**: [HUD PDR Data](https://www.huduser.gov/portal/datasets/pdrdata.html)
*   **Key Capabilities**: Fair market rent and housing affordability modeling.

## 14. 🏭 Manufacturing
*   **Primary Source**: [Industrial Statistics Agency Industrial Statistics](https://stat.Industrial Statistics Agency.org/)
*   **Key Capabilities**: Industrial production indices and efficiency benchmarking.

## 15. 🎬 Media & Entertainment
*   **Primary Source**: [IMDb Datasets](https://www.imdb.com/interfaces/)
*   **Secondary Source**: [Spotify Trends (Simulated)]
*   **Key Capabilities**: Cultural trend analysis and content rating distributions.

## 16. 🎯 Decision Support
*   **Source**: Multi-Sector Integrated Core.
*   **Key Capabilities**: Cross-sector correlation and agent reasoning validation.

---

## 🛠️ Unified Integration Logic
All sectors leverage the `BaseProvider.load_raw_data` abstraction, supporting:
1.  **Local Files**: CSV/Excel/JSON relative to project root.
2.  **Web URLs**: Direct HTTP/S fetching with exponential backoff.
3.  **Simulation Fallback**: High-fidelity mock generation if API keys or local files are missing, ensuring 100% execution coverage.
