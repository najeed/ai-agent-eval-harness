# AES Scenario Schema for dataproc-engine

To ensure `dataproc-engine` outputs are consumable by AES evaluation agents, the engine must transform **Ground Truth Records** into **Evaluation Scenarios**.

## Target JSON Schema (Aligns with AES Core)

```json
{
  "scenario_id": "string (e.g., finance-sec-aapl-assets)",
  "version": "2.0.0",
  "title": "string",
  "description": "string",
  "industry": "string",
  "use_case": "string",
  "core_function": "string",
  "tasks": [
    {
      "task_id": "string",
      "description": "The specific question or instruction for the agent.",
      "expected_outcome": "The verifiable ground truth derived from dataproc_engine.",
      "success_criteria": [
        {
          "metric": "generic_accuracy",
          "threshold": 1.0
        }
      ]
    }
  ],
  "provenance": {
    "source_url": "URL to the SEC/FRED source",
    "retrieval_timestamp": "ISO-8601"
  }
}
```

## Generation Strategy
1.  **Template-Driven**: Each `Provider` (e.g., `FinanceProvider`) defines a set of scenario templates (e.g., "Asset Verification", "Revenue Comparison").
2.  **Data Injection**: The `DatasetEngine` injects real, verified values from the extraction phase into these templates.
3.  **Output**: Scenarios are saved as individual JSON files in `industries/{industry}/scenarios/` for ingestion by the AES runtime.
