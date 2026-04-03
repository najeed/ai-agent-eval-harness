# README: Auto-Translation (The Rosetta Stone)

Learn how to rapidly bootstrap evaluation scenarios from unstructured documentation using the `auto-translate` system.

## 🎯 Objectives
- Transform a raw Markdown PRD into a structured AES JSON scenario.
- Understand how the harness parses "Human Intent" into "Machine Truth."
- Perform a schema validation check on the generated benchmark.

## 🚀 Steps

### Step 1: The Raw PRD
Look at `sample_prd.md`. It's a technical specification for an industrial reactor startup sequence, written in human-readable prose.

### Step 2: Run the Translation Script
This script will call the `auto-translate` command to parse the PRD and generate a valid AES JSON file.
```bash
python walkthroughs/Phase 3 - Intelligence & Complexity - Advanced/auto_translation/Step_1_Translate_to_AES.py
```

### Step 3: Validate the AES JSON
Once generated, look at the resulting `reactor_startup.json`. You'll see that the paragraphs have been broken down into discrete "Workflow Nodes" with specific "Expected Outcomes."

## 📊 Key Concepts
- **AES Standard**: The `Autonomous Evaluation Standard` (AES) is the JSON schema that all benchmarks follow.
- **Bootstrapping**: This feature is critical for legacy industries where formal benchmarks do not yet exist, but technical manuals are abundant.

---
*Ready to translate the legend? Run the [Step_1_Translate_to_AES.py](./Step_1_Translate_to_AES.py) script next!*








