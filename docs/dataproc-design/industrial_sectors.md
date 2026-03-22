# 🌐 Industrial Sectors & Gold Standard Guide

The `dataproc-engine` supports 8 core industrial sectors, each hardened with "Gold Standard" datasets and mission-critical schema enforcement.

## 1. 🏦 Finance
*   **Primary Source**: [SEC EDGAR](https://www.sec.gov/edgar/searchedgar/companysearch) (Public Audited Data)
*   **Secondary Source**: [FRED](https://fred.stlouisfed.org/) (Macroeconomic Indicators)
*   **Benchmarks**: [UCI Credit Approval](https://archive.ics.uci.edu/dataset/27/credit+approval)
*   **Key Capabilities**: XBRL-aware extraction, cross-CIK correlation, and credit risk probability modeling.

## 2. 🏥 Healthcare
*   **Primary Source**: [CMS Hospital General Info](https://data.cms.gov/provider-data/dataset/x7fx-mvoc)
*   **Benchmarks**: [MIMIC-IV Clinical Database](https://mimic.mit.edu/) (Simulated)
*   **Key Capabilities**: Deep clinical lab-event simulation, PII scrubbing (HIPAA-compliant), and patient experience metric normalization.

## 3. ⚡ Energy
*   **Primary Source**: [EIA Open Data](https://www.eia.gov/opendata/) (WTI/Brent/NatGas Prices)
*   **Benchmarks**: [IEA World Energy Balances](https://www.iea.org/data-and-statistics/data-product/world-energy-balances)
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

---

## 🛠️ Unified Integration Logic
All sectors leverage the `BaseProvider.load_raw_data` abstraction, supporting:
1.  **Local Files**: CSV/Excel/JSON relative to project root.
2.  **Web URLs**: Direct HTTP/S fetching with exponential backoff.
3.  **Simulation Fallback**: High-fidelity mock generation if API keys or local files are missing, ensuring 100% execution coverage.
