# README: Discovery & Exploration

This module will teach you how to navigate the Scenario Catalog and find the industrial benchmarks you need.

## 🎯 Objectives
- List all scenarios in the harness.
- Perform a targeted search for specific industries (Finance/Telecom).
- Understand how scenarios are categorized.

## 🚀 Steps

### Step 1: The Master List
Run the basic list command to see the entire industrial map.
```bash
multiagent-eval list
```

### Step 2: Search for Finance
Need to find benchmarks related to banking and ledgers? Use the query filter.
```bash
multiagent-eval list --query finance
```

### Step 3: Run the Discovery Script
For a guided experience, execute the interactive script.
```bash
python walkthroughs/Phase 1 - Foundations - Beginner/discovery/Step_1_Run_Discovery.py
```

## 📊 Key Concepts
- **Industries**: Scenarios are organized into sectors (e.g., `finance/`, `telecom/`).
- **Discovery**: The `ScenarioCatalog` class (singleton) caches this index for high performance across evaluations.

---
*Ready to dive in? Run the [Step_1_Run_Discovery.py](./Step_1_Run_Discovery.py) script next!*








