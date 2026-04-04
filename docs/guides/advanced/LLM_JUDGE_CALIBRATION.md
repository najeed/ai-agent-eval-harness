# Advanced Guide: LLM Judge Calibration

This guide explains how to measure and improve the alignment between automated LLM judges and human-labeled ground truth scoring.

## Why Calibrate?
LLM-as-a-judge is powerful but can be prone to "self-correction bias" or "vagueness." Calibration ensures that a `0.8` semantic score accurately reflects the level of correctness required by auditors and industry stakeholders.

## The Calibration Workflow

### 1. Labeling Ground Truth
Ensure your scenarios include a `human_score` field in the criteria metadata. This represents the "Gold Standard" from a subject matter expert.
```json
{
  "metric": "luna_judge_score",
  "threshold": 0.8,
  "human_score": 0.9,
  "required": true,
  "judge_config": {
    "judge_rubric": "clinical_safety"
  }
}
```

> [!TIP]
> **Use the `required: true` flag** during calibration. This prevents the benchmark from falling back to Jaccard similarity if your judge provider is misconfigured, ensuring that your calibration metrics always reflect actual LLM performance.

---

### 2. Execution
Run your evaluation as normal. The harness will record the judge's score alongside the human score in the flight recorder (`run.jsonl`).

```bash
multiagent-eval evaluate --path scenarios/healthcare/
```

---

### 3. Running the Calibrator
Use the `calibrate` command to generate an alignment report.

```bash
multiagent-eval calibrate --path runs/latest_run.jsonl
```

## Interpreting Alignment Metrics

### Pearson Correlation
- **0.9 - 1.0**: 🟢 Excellent. The judge and human are in lock-step.
- **0.7 - 0.9**: 🟡 Good. The judge captures the general trend but may slightly over/under estimate.
- **< 0.7**: 🔴 Poor. The judge is not reliably capturing the human nuance. Review your **Rubric** or **Temperature**.

### Mean Absolute Error (MAE)
This measures the average distance between the judge and human score. An MAE of `0.05` means the judge is typically within 5% of the human score.

## Improving Alignment

### 1. Select the Right Rubric
Switch from `generic` to an industry-specific rubric (e.g., `fiduciary_accuracy`) to give the LLM more context on what "correctness" means in your domain.

### 2. Adjust Temperature
For judges, a `judge_temperature` of `0.0` is recommended for maximum reproducibility.

### 3. Refine the Prompt
You can register custom rubrics via a plugin using the `RubricRegistry` in `eval_runner.rubrics`.
