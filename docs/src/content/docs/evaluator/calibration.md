---
title: LLM Judge Calibration
description: Measure and improve the alignment between automated LLM judges and human-labeled ground truth scoring.
---

Calibration compares recorded evaluation values with human labels matched by
`task_id`. It measures agreement on the supplied sample; it does not establish
that a judge is correct for every task or prevent all fallback scoring.

## Supply human labels

Create `data/golden_labels.json` containing a task-ID-to-number map. Use the
exact task IDs in the run's `evaluation` events, not display titles:

```json
{
  "task-a": 0.9,
  "task-b": 0.2
}
```

Then calibrate an existing provider-owned run:

```bash
agentv calibrate --run-id YOUR_RUN_ID --golden data/golden_labels.json
agentv calibrate --run-id YOUR_RUN_ID --golden data/golden_labels.json --plot
```

The CLI reads events through the active RunStorageProvider. Alternatively, input
events can mark human `evaluation` values with `metadata.human=true`, or put a
numeric `metadata.human_label` on a `run_start`/`task_start` event with the matching
task ID. External golden labels override recorded human labels. A criterion's
`human_score` is not an input to this utility.

## Interpret the report

- **MAE**: Mean absolute distance between paired numeric scores.
- **Pearson correlation**: Linear association, reported as zero for fewer than
  two pairs or a zero denominator. Correlation alone does not establish agreement.
- **F1 threshold sweep**: Judge thresholds from 0 to 1 in steps of 0.05, compared
  with human success at 0.5. The report suggests the best threshold on this sample;
  validate it on held-out labels before adopting it.

The utility keeps the last non-human evaluation value and last human evaluation
value for each task ID. It does not separately aggregate multiple metrics or
attempts for that ID; prepare a suitable event set when analyzing repeated
measurements. No aligned pairs means calibration aborts. Cohen/Fleiss Kappa are
not computed. `--plot` writes `calibration_plot.png` in the current directory when
matplotlib and numpy are available; otherwise the utility reports plotting skipped.

## Judge configuration and fallback

The default judge provider is `ollama`; `JUDGE_MODEL` is unset. Configure a model
and suitable rubric explicitly. `luna_judge_score` returns 1 when the expected
outcome is absent or already exactly matches the answer. `required: true` rethrows
provider initialization failures, but generation/parsing errors can still reach
fallback scoring. It is not a guarantee that every score came from model inference.
Record the scoring path when interpreting calibration results. See
[provider configuration](/builder/providers/).
