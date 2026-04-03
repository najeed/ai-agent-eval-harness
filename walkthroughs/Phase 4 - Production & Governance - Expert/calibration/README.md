# README: Calibration (The Golden Ratio)

Learn how to mathematically align your LLM Judges with human expertise using the `calibrate` system.

## 🎯 Objectives
- Understand **Spearman's Rho (Correlation)** and why it's critical for industrial evaluation.
- Generate a **Golden Truth Manifest** containing human labels.
- Execute the `calibrate` command to find the optimal success threshold.

## 🚀 Steps

### Step 1: Generate the Golden Truth
We need a set of evaluation results that have been "Blessed" by a human expert.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/calibration/Generate_Golden_Truth.py"
```

### Step 2: Run the Calibration
This interactive script will call the `calibrate` command as it compares the Judge's raw scores against the Human's binary (Pass/Fail) labels.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/calibration/Step_1_Run_Calibration.py"
```

### Step 3: Inspect the Veracity Report
After the run, check the output. You'll see the **Rho Score** (aim for >0.7) and the **Optimal Threshold**. If the Rho is too low, you may need a more advanced Judge model (like Luna-2).

## 📊 Key Concepts
- **Spearman's Rho**: A statistical measure of the monotonic relationship between two variables. In our case, it's the agreement between Machine and Human.
- **Golden Manifest**: A JSON mapping that pairs evaluation `run_ids` with human-determined `ground_truth` values.

---
*Ready to find the Golden Ratio? Run the [Generate_Golden_Truth.py](./Generate_Golden_Truth.py) script next!*







