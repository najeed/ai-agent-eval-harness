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
3.  Populate the JSON file using the structure defined in the [Evaluation Guide](guide.md). Use existing scenarios as a reference.

## Step 3: Document Core Functions

1.  Add your new industry, its use cases, and core functions to the [Core Functions Guide](../builder/core-functions.md). These constructs relate to the `industry`, `use_case`, and `core_function` fields in your JSON files.
2.  Define the core functions to document their scope for future evaluators.

## Step 4: Include Synthetic Datasets

Realistic environments require data. If your scenarios require data (e.g., a CSV of customer transactions), you should link them via the `dataset` attribute.
To generate highly realistic dummy data for your new industry, use the built-in generation script:

```bash
python scripts/generate_industry_datasets.py --industry YOUR_INDUSTRY
```

This script creates a `records.csv` with industry-specific schemas (e.g., policy numbers for insurance, flight routes for airlines) and places it directly in your `datasets/` folder for immediate use.

### Validation

All scenarios are validated at load time against the AES schema. Your scenario **must** include these required fields:

**Scenario level:**
- `scenario_id`, `title`, `description`, `use_case`, `core_function`, `industry`, `tasks`
- (Optional) `initial_state`, `policies`

**Task level** (each item in `tasks`):
- `task_id`, `description`, `expected_outcome`, `success_criteria`
- (Optional) `expected_state_changes`

Run schema validation locally:
```bash
python -c "from eval_runner.loader import load_scenario; from pathlib import Path; load_scenario(Path('industries/YOUR_INDUSTRY/scenarios/YOUR_SCENARIO.json'))"
```

## Step 5: Verify in Visual Debugger

Launch the dashboard to ensure your new industry and scenarios are appearing correctly in the library:

```bash
agentv console
```

Navigate to the **Library** tab to view your JSON structure and trigger a test run visually.
