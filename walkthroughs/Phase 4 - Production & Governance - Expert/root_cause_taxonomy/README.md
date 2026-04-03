# README: Root Cause Taxonomy (The Forensic Heatmap)

Learn how to diagnostically categorize agentic failures and visualize systemic weaknesses across your industrial fleet.

## 🎯 Objectives
- Categorize 10 failures into standard groups (**Reasoning**, **Tool Use**, **Domain Knowledge**).
- Understand the **Root Cause Taxonomy** used in the MultiAgentEval framework.
- Generate a **Failure Heatmap** (`failure_heatmap.json`) to visualize technical debt.

## 🚀 Steps

### Step 1: Generate the Failure Dataset
Before we can perform our analysis, we need a "Bundle" of failed traces.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/root_cause_taxonomy/Generate_Failure_Bundle.py"
```

### Step 2: Run the Diagnostic Analysis
This interactive script will guide you through the process of analyzing the root causes for the 10 failures.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/root_cause_taxonomy/Step_1_Categorize_and_Map.py"
```

### Step 3: Inspect the Heatmap
Once the analysis is complete, check the `failure_heatmap.json`. You'll see which technical capabilities (e.g., "Reasoning") are currently the biggest bottleneck for your fleet.

## 📊 Key Concepts
- **Taxonomy Standards**: We use the **AES-Forensic-v1.2** categories to ensure that every failure is recorded using the same nomenclature.
- **Systemic Vulnerabilities**: By looking at the heatmap, you can decide whether to spend your next engineering sprint on "Better Reasoning" or "More Domain Knowledge."

---
*Ready to build the heatmap? Run the [Generate_Failure_Bundle.py](./Generate_Failure_Bundle.py) script next!*







