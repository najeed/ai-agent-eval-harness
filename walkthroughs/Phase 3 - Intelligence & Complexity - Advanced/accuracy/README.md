# Walkthrough: Industrial Judge Calibration

Welcome to the MultiAgentEval Calibration walkthrough! This guide will teach you how to ensure your AI "Judge" is making consistent and accurate evaluation decisions compared to human benchmarks.

## 🎯 Objectives
- Understand the difference between **Judge Scores** and **Human Ground Truth**.
- Measure the **statistical agreement** between AI and Human evaluations.
- Use **Auto-Thresholding** to optimize your pass/fail criteria.

## 📂 Artifacts in this Walkthrough
1. **[Step_1_Evaluation_Trace.jsonl](./calibration/Step_1_Evaluation_Trace.jsonl)**: A raw evaluation trace containing judge scores for 5 finance tasks.
2. **[Step_2_Human_Ground_Truth.json](./calibration/Step_2_Human_Ground_Truth.json)**: The "Golden Label" manifest representing the human standard.
3. **[Step_3_Run_Calibration.py](./calibration/Step_3_Run_Calibration.py)**: The interactive execution script.
4. **[Step_4_Mutated_Bad_Judge.jsonl](./calibration/Step_4_Mutated_Bad_Judge.jsonl)**: A sample of an 'Inaccurate Judge' to see how the system flags it.

## 🚀 Get Started

### 1. Mock Graphic: What Good Calibration Looks Like
When plotting is enabled, you'll see a scatter plot resembling this:

```text
Judge AI Score (Y)
    ^
1.0 |                * (Correct Success)
    |             *
    |          *
0.5 |       *  (Auto-Threshold Suggested Here)
    |    *
    |* (Correct Failure)
0.0 +----------------------------> Human Label (X)
    0.0             0.5             1.0
```

### 2. Inspect the Trace
Open **Step 1**. Note how the `GPT-4o` judge has assigned scores between `0.30` and `0.95`. At this stage, we don't know if these scores are "correct" according to our internal standards.

### 2. Compare with Ground Truth
Open **Step 2**. This is a mapping where humans have explicitly labeled each task as either `1.0` (Complete Success) or `0.0` (Complete Failure).

### 3. Run the Walkthrough
Execute the follow command from your terminal:
```bash
python walkthroughs/calibration/Step_3_Run_Calibration.py
```

### 4. Observe the 'Bad Judge'
The walkthrough script also runs **Step 4**. Note how the metrics change when a judge provides 'fake success' scores (high values for human failures).
- **MAE** will spike.
- **F1 Score** will drop significantly.

## 📊 Interpreting Your Results

> [!TIP]
> **Correlation (Rho)**: A score of `> 0.8` means your judge's relative ranking is excellent, even if its absolute scores are slightly higher or lower than the human's.
> **MAE (Mean Absolute Error)**: If MAE is `> 0.3`, your judge might be "hallucinating" success in subtle ways.
> **Recommended Threshold**: This is the "Magic Number". If the calibrator suggests `0.65`, you should update your scenario's `threshold` parameter to match!

---
*MultiAgentEval (v1.2.3) - Guided Experience Layer*








