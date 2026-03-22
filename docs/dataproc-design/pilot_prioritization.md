# Industry Dataset Prioritization Report

This report evaluates and scores key industries based on the availability, feasibility, and robustness of their public, factual data sources.

## Scoring Methodology
*   **Feasibility (1-10)**: Ease of automated extraction. High scores imply REST APIs, structured formats (JSON/CSV), and clear documentation.
*   **Robustness (1-10)**: Reliability and authority of the source. High scores imply official government/institutional sources with high historical depth.

## Industry Mapping & Scoring

| Industry | Primary High-Quality Source(s) | Feasibility | Robustness | Overall Score | Recommendation |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Finance** | SEC EDGAR, FRED (Federal Reserve) | 10 | 10 | **10.0** | **Primary Pilot**. Audited, structured XBRL with robust govt APIs. |
| **Transportation**| GTFS (Real-time), US DOT | 10 | 9 | **9.5** | **Top Tier**. GTFS is a perfect global standard for automated ETL. |
| **eCommerce** | UCI Online Retail, Olist (Brazil) | 9 | 9 | **9.0** | **Top Tier**. Perfectly structured transactional logs, ideal for one-shot automation. |
| **Agriculture** | USDA NASS (Quick Stats), FAOSTAT | 9 | 9 | **9.0** | Excellent structured data with well-documented REST APIs. |
| **Energy** | EIA (Energy Information Admin), IEA | 8 | 9 | **8.5** | Strong reliability and clean time-series data via API. |
| **Logistics** | Industry SOPs, Dangerous Goods (SDS), DOT | 8 | 8 | **8.0** | High-signal, but SDS parsing requires more complex text-processing agents. |
| **Telecom** | Ofcom, FCC, GSMA, Ookla Open Data | 8 | 8 | **8.0** | Good regulatory benchmarks but more variable data structures. |
| **Professional Services**| BLS, O*NET, Professional Journals | 7 | 8 | **7.5** | High-value, but actual deliverables are often unstructured or proprietary. |
| **Healthcare** | CMS (Medicare), CDC, OpenFDA | 6 | 9 | **7.5** | Strong legal sources, but HIPAA/de-identification adds high implementation friction. |
| **Manufacturing** | ISO Standards, Industry SOPs, NIST | 7 | 8 | **7.5** | Complex technical reasoning required over heterogeneous doc types. |
| **Legal** | PACER, CaseLaw Access Project, LegalBench| 5 | 9 | **7.0** | Highest source robustness but lowest feasibility (paywalls/PDFs). |

## Deep Dive Analysis

### 1. Finance (The Gold Standard)
*   **Why**: The SEC is legally mandated to provide transparent, audited data for all public companies. FRED provides the global baseline for macro markers.
*   **ETL Advantage**: XBRL allows for cell-level financial reasoning without brittle text scraping.

### 2. Energy & Environment
*   **Why**: The EIA provides standardized, granular data on energy flows, prices, and emissions.
*   **ETL Advantage**: Very clean tabular data and well-documented REST APIs.

### 3. Professional, Scientific, and Technical Services
*   **Why**: Identified as a top-tier U.S. GDP contributor ($2T+). Covers high-value knowledge work occupations (Consultants, Engineers).
*   **ETL Advantage**: Large volume of "predominantly digital" scenarios and deliverables.

### 4. Logistics & Supply Chain (Industrial SOPs)
*   **Why**: Industry benchmarks highlight numerous scenarios here. Dangerous Goods classification and SDS processing are factual and require high reasoning precision.
*   **ETL Advantage**: Clear, rule-based logic from safety data sheets and shipping regulations.

### 5. Manufacturing (Technical SOPs)
*   **Why**: Fundamental to GDP. Involves high-reasoning scenarios over CAD files, quality control lists, and technical standards.
*   **ETL Advantage**: High signal from NIST and ISO documentation.

## Prioritization Summary
Based strictly on **Implementation Feasibility** and **Source Robustness**:
1.  **Finance** remains the #1 choice due to the SEC's mandated use of machine-readable XBRL.
2.  **Transportation** and **eCommerce** are elevated to the "Top Tier" because their primary datasets (GTFS and Olist/UCI) are uniquely standardized and easy to automate.
3.  **Agriculture** and **Energy** follow closely with high-quality REST APIs.
4.  **Healthcare** and **Legal** are deprioritized as pilot candidates due to significant implementation friction (privacy laws and paywalls).
