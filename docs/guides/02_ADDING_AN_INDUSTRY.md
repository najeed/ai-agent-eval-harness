<!-- docs/guides/02_ADDING_AN_INDUSTRY.md -->

# Guide: Adding a New Industry

This guide provides a step-by-step process for adding a new industry to the evaluation harness.

## Step 1: Create the Directory Structure

1.  Navigate to the `industries/` directory in the root of the project.
2.  Create a new folder for your industry. The name should be lowercase and use underscores instead of spaces (e.g., `real_estate`, not `Real Estate`).
3.  Inside your new industry folder, create two sub-folders:
    -   `scenarios`
    -   `datasets`

## Step 2: Add Your First Scenario

1.  Inside the `scenarios` folder, you may want to create sub-folders for different use cases (e.g., `fraud_detection` in the `finance` industry).
2.  Create your first scenario `.json` file. The name should be numbered and descriptive (e.g., `01_mortgage_application_check.json`).
3.  Populate the JSON file using the structure defined in the [Evaluation Guide](01_EVALUATION_GUIDE.md). Use existing scenarios as a reference.

## Step 3: (Optional) Add Datasets

If your scenario requires external data (like a CSV of transactions or a JSONL file of user profiles), add the data file to the `datasets` directory. Be sure to anonymize any sensitive information.

## Step 4: Submit a Pull Request

Once you have created the directory structure and added at least one complete scenario, please submit a Pull Request. In the description, briefly explain the industry and the use cases you are starting to build out.

Thank you for helping expand the reach of this project!
