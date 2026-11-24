---
title: Adding a New Industry
description: Step-by-step guide for expanding the harness with new vertical-specific industries and scenarios.
---

This guide provides a step-by-step process for adding a new industry to AgentV.

## Step 1: Create the Directory Structure

1.  Navigate to the `industries/` directory in the root of the project.
2.  Create a new folder for your industry. The name should be lowercase and use underscores instead of spaces (e.g., `real_estate`, not `Real Estate`).
3.  Inside your new industry folder, create two sub-folders:
    -   `scenarios`
    -   `datasets`

## Step 2: Add Your First Scenario

1.  Inside the `scenarios` folder, you may want to create sub-folders for different use cases (e.g., `crop_management` in the `agriculture` industry).
2.  Create your first scenario `.json` file. The name should be numbered and descriptive (e.g., `01_mortgage_application_check.json`).
3.  Populate the JSON file using the structure defined in the [Evaluation Guide](/evaluator/guide/). Use existing scenarios as a reference.

## Step 3: Document Core Functions

1.  Add your new industry, its use cases, and core functions to the [Core Functions Guide](/builder/core-functions/). These constructs relate to the `industry`, `use_case`, and `core_function` fields in your JSON files.
2.  Define the core functions to document their scope for future evaluators.

## Step 4: Include Synthetic Datasets

Realistic environments require data. If your scenarios require data (e.g., a CSV of customer transactions), you should link them via the `dataset` attribute.

Place your industry-specific database or transaction CSV/JSON files directly inside your industry's `datasets/` directory (e.g. `industries/<your_industry>/datasets/records.csv`), and reference them in your scenario metadata.

### Validation

All scenarios are validated at load time against the AES schema. Your scenario **must** include these required fields:

**Scenario level:**
- `metadata`: Requires `id`, `name`, and `compliance_level` (`Standard`, `Gold`, or `Regulatory_Audit`); `capabilities` is optional.
- `aes_version`: Required at the root as numeric `1.4`.
- `evaluation`: Required root object, even when empty.
- `workflow`: Contains `nodes` and `edges`.

**Task Node level** (each item in `workflow.nodes`):
- `id` and `task_description` are schema-required; declare meaningful `success_criteria` and/or `expected_outcome` assertions for evaluable coverage.
- (Optional) `expected_outcome`

Run schema validation locally:
```bash
agentv aes validate --path industries/YOUR_INDUSTRY/scenarios/YOUR_SCENARIO.json
```

## Step 5: Verify in Visual Debugger

Launch the dashboard to ensure your new industry and scenarios are appearing correctly in the library:

```bash
agentv console
```

Navigate to the **Library** tab to view your JSON structure and trigger a test run visually.
