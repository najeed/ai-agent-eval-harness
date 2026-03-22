# 🏥 Healthcare Sector: Deep-Dive Guide

## 🛰️ Data Source Strategy
The healthcare sector prioritizes data veracity and privacy-safe clinical benchmarks.

### 1. CMS (Centers for Medicare & Medicaid Services)
*   **Role**: Primary source for hospital quality and patient experience metrics.
*   **Logic**:
    *   Fetch **Hospital General Information** (Public Dataset).
    *   Field focus: `Star Rating`, `Patient Experience`, `Safety of Care`.
    *   **Normalization**: Standardize Provider IDs and Facility Names.

### 2. MIMIC-IV (Clinical Benchmark Simulation)
*   **Role**: Gold standard for clinical reasoning (ICU-level events).
*   **Logic**:
    *   **Credentialed Access**: Requires PhysioNet DUA for real-world records.
    *   **Zero-Mock Simulation**: Ships with high-fidelity simulated lab events (`hosp/labevents`).
    *   **Reasoning Injection**: Correlate patient quality scores with hospital efficiency metrics.

## 🛠️ ETL & Transformation
1.  **PII Scrubbing**: Automatic redaction of sensitive patient identifiers using the `BaseProvider` scrubbing layer.
2.  **Clinical Mapping**: 
    *   **Logic**: Map medical events to `StandardSchema` trajectories.
    *   **Sentiment**: Patient feedback analysis from unstructured CMS comments.

## 🛡️ Robustness & Compliance
*   **HIPAA Compliance**: The engine enforces a strict "No PII on Disk" policy for extraction.
*   **Veracity**: All hospital records are tagged with a direct CMS dataset ID for provenance.
*   **Fallback**: High-fidelity simulation for [MIMIC-IV](https://mimic.mit.edu/) is active by default.
