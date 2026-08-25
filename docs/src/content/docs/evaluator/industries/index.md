---
title: Industrial Sector Taxonomy & Benchmark Catalog
description: Comprehensive catalog of 52 industrial sectors and domain benchmark suites supported by AgentV.
---

AgentV provides high-fidelity, sector-specific behavioral benchmarks, data extraction tools, and evaluation scenarios across **52 distinct industrial and operational domains**. Each domain includes curated datasets, sector-specific world shims, regulatory policy rules, and automated evaluation metrics.

---

## 🏛️ Comprehensive Domain Catalog (52 Sectors)

### 1. Financial Services & Professional Practice
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **Finance** | Commercial banking, algorithmic trading, KYC, credit risk. | SEC EDGAR, FRED, Basel III, PCI-DSS |
| **Accounting** | Ledger auditing, GAAP/IFRS reconciliation, balance sheet validation. | FASB, IASB, General Ledger exports |
| **Audit** | Forensic financial auditing, internal controls, Sox compliance. | PCAOB, COSO framework, AICPA |
| **Tax** | Corporate and individual tax planning, cross-border VAT/GST, IRS codes. | IRS Tax Codes, OECD BEPS, Transfer Pricing rules |
| **Insurance** | Actuarial risk modeling, claims adjudication, policy underwriting. | NAIC, ACORD, Claim adjudication logs |
| **Consulting** | Management consulting frameworks, strategy synthesis, financial modeling. | Enterprise KPI dashboards, Market benchmarks |
| **Legal** | Contract analysis, regulatory compliance, litigation discovery, NDAs. | CourtListener, SEC filings, CaseLaw databases |

### 2. Healthcare, Life Sciences & Biotech
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **Healthcare** | Clinical diagnostics, EHR navigation, HIPAA privacy, medical triage. | CMS, WHO, FHIR, HIPAA Title II |
| **Pharmaceuticals & Life Sciences** | Drug discovery workflows, clinical trials, FDA approval filings. | FDA Orange Book, PubMed, ClinicalTrials.gov |
| **Demographics** | Population health epidemiology, census analysis, actuarial statistics. | CDC, WHO Global Health Observatory |

### 3. Critical Infrastructure, Energy & Environment
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **Energy** | Grid load forecasting, renewable dispatch, wholesale power markets. | EIA, IEA, FERC, SmartGrid telemetry |
| **Oil & Gas** | Upstream drilling telemetry, midstream pipeline SCADA, refinery scheduling. | API standards, SPE, Pipeline SCADA logs |
| **Utilities** | Water treatment, electrical distribution, smart meter telemetry. | AWWA, NERC CIP, Smart Meter AMI |
| **Environment** | Carbon accounting, GHG emissions modeling, EPA environmental permits. | EPA Envirofacts, IPCC emissions factors, GHG Protocol |
| **Mining** | Ore extraction planning, geotechnical safety, environmental compliance. | MSHA, USGS Mineral Resources |

### 4. Aerospace, Defense & National Security
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **Aerospace** | Flight trajectory planning, avionics subsystem monitoring, FAA compliance. | FAA, NASA telemetry, ADS-B exchanges |
| **Airline** | Fleet dispatch, crew scheduling, baggage routing, disruption recovery. | IATA, DOT Air Travel statistics |
| **Defense** | Tactical mission planning, secure command & control, defense procurement. | DoD standards, MIL-STD, NATO STANAG |
| **Cybersecurity** | Threat intelligence hunting, SIEM log analysis, SOC automated response. | MITRE ATT&CK, NIST SP 800-61, CVE/NVD |

### 5. Manufacturing, Engineering & Heavy Industries
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **Manufacturing** | Shop floor PLC automation, predictive maintenance, bill of materials. | ISA-95, ISO 9001, Industrial IoT telemetry |
| **Heavy Industries** | Metallurgy, blast furnace monitoring, heavy equipment logistics. | OSHA, Industrial SCADA logs |
| **Automotive** | Supply chain parts sequencing, CAN bus telemetry, vehicle recall triage. | NHTSA, SAE International standards |
| **Chemicals** | Batch reactor recipe optimization, Hazmat compliance, SDS generation. | OSHA HazCom, GHS, REACH regulations |
| **Construction** | BIM model parsing, structural safety checklists, contractor scheduling. | OSHA 1926, AIA documentation |

### 6. Logistics, Transportation & Smart Cities
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **Transportation** | Multi-modal freight optimization, fleet maintenance, DOT compliance. | USDOT, FMCSA, Telematics APIs |
| **Logistics & Warehousing** | WMS inventory optimization, automated pick/pack routing, parcel track. | WMS feeds, EDI 204/214/310 |
| **Ports** | Container terminal berth allocation, customs inspection, vessel scheduling. | AIS vessel tracking, Maritime Port Authority feeds |
| **Smart Cities** | Traffic signal adaptive control, municipal utility dispatch, urban planning. | City OpenData APIs, SCATS/SCOOT |

### 7. Commerce, Retail & Media
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **Ecommerce** | Dynamic pricing, catalog recommendation, cart checkout fraud. | Shopify/Stripe API schemas, Web telemetry |
| **Retail** | POS reconciliation, shrinkage prevention, store shelf inventory. | POS transaction logs, GS1 barcodes |
| **Wholesale** | Bulk B2B ordering, trade credit terms, distributor inventory sync. | B2B EDI 850/855/856 |
| **Media & Entertainment** | Rights management, content metadata tagging, streaming QoS metrics. | SMPTE, EIDR, Streaming CDN logs |
| **Journalism** | Automated fact-checking, source attribution, breaking news synthesis. | AP Stylebook, Reuters Wire, FactCheck.org |
| **Marketing & Advertising** | Multi-channel ad attribution, campaign bidding, compliance review. | Google Ads API, Meta Marketing API |

### 8. Technology, Telecom & Public Administration
| Sector | Description | Primary Data Sources & Standards |
| :--- | :--- | :--- |
| **IT Product** | Software release management, CI/CD triage, defect prioritization. | GitHub/GitLab APIs, Jira, Bugzilla |
| **IT Service** | ITSM ticket triage, SLA escalation, ITIL service catalog workflows. | ServiceNow schemas, ITIL v4 |
| **Telecom** | 5G RAN telemetry, OSS/BSS billing mediation, network fault management. | FCC, ITU, 3GPP standards |
| **Public Sector** | Citizen service entitlement, permit approval, FOIA request processing. | US Census, Data.gov, HUD datasets |
| **Education** | Student assessment scoring, curriculum alignment, LMS administration. | Ed-Fi standard, Canvas/Moodle LTI |
| **Hospitality** | Hotel PMS reservations, dynamic revenue management, guest service. | HTNG standards, Sabre/Amadeus GDS |
| **Housing & Real Estate** | Property appraisal, MLS listings parsing, lease agreement validation. | MLS RETS/RESO, HUD regulations |
| **Human Resources** | Applicant resume parsing, benefits enrollment, payroll tax calculation. | HR-XML, EEOC compliance rules |
| **Sports & Venues** | Stadium crowd flow, ticketing anti-scalping, performance analytics. | SportsStats feeds, Ticketing APIs |
| **Tourism** | Destination travel itinerary synthesis, visa requirements, booking sync. | IATA Timatic, Tourism Board APIs |

### 9. Advanced Behavioral & Systemic Benchmarks
| Sector | Description | Evaluation Focus |
| :--- | :--- | :--- |
| **Cross-Industry** | Multi-sector negotiations (e.g. Healthcare provider negotiating with Insurer). | Complex inter-agent state synchronization |
| **Ethical Guardrails** | Adversarial jailbreak attempts, PII exfiltration, bias triggers. | NIST AI 100-1 Safety & Security floors |
| **Interactive Complexity**| Human-in-the-loop (HITL) approval gates, asynchronous re-planning. | Turn state serialization & pause/resume |
| **Simulations** | High-fidelity mock operating systems, synthetic database clusters. | VFS state delta & isolation boundaries |
| **Unstructured** | Raw messy documents, scanned PDFs, ambiguous user prompts. | Robust extraction & ambiguity resolution |

---

## 🚀 Running Industry Benchmarks

To execute evaluations on any sector:

```bash
# Run batch evaluation on finance scenarios
agentv evaluate --path industries/finance/scenarios/ --attempts 3

# Run healthcare HIPAA compliance audit
agentv run --path industries/healthcare/scenarios/hipaa_audit.json

# Search the catalog for legal discovery scenarios
agentv catalog-search "legal e-discovery"
```
