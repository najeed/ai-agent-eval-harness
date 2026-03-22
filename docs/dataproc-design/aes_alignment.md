# AES Dataset Alignment Strategy

The `dataproc-engine` is designed to provide the underlying verifiable ground truth that fuels the agent evaluation process. This document outlines how extracted datasets are aligned with existing AES scenarios.

## 1. Mapping Extraction to Scenarios

| Scenario ID | Task Requirement | dataproc Dataset Support |
| :--- | :--- | :--- |
| `scenario-39dd9c3d` | Verify audit trail / retrieval. | `entity_name` and `status` mapped to SEC CIK and filing status. |
| `finance-cf-11255` | Perform 'what-if' modeling. | Historical revenue/sales trends (10-K time-series). |
| *Future Scenarios* | General Knowledge Retrieval. | Full corporate facts (JSON Knowledge Base). |

## 2. Output Formatting (AES Standard)

To be useful for agents, the engine supports two primary output formats:

### A. Tabular CSV (Legacy Support)
Matches existing `industries/{industry}/datasets/` schemas. Useful for agents using simple table-lookup tools.
*   **Location**: `industries/finance/datasets/finance_records.csv`
*   **Fields**: `record_id`, `entity_name`, `status`, `revenue`, `assets`, `updated_at`.

### B. High-Signal JSONL (Knowledge Base)
Rich, hierarchical data for RAG-enabled or sophisticated reasoning agents. Contains technical units, units of measure, and deep source provenance.
*   **Location**: `dataproc_engine/output/{industry}_kb.jsonl`

## 3. Direct Integration Workflow
By using the `--target industries` flag, the engine will:
1.  Extract live ground truth.
2.  Format it to match the AES target schema.
3.  Overwrite the local `industries/{industry}/datasets/` files.
4.  Allow for immediate re-running of agent evaluations against the latest data.
