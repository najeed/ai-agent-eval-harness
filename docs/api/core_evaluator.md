# 📦 API Reference: Core Evaluator

The `eval_runner` core provides the main orchestration logic for agentic evaluations.

## `engine.run_evaluation`
Executes a single evaluation scenario.

**Parameters:**
- `scenario`: The scenario object to evaluate.
- `attempts`: Number of attempts for pass@k.

**Returns:**
- `EvaluationResults`: Summary of the run, including all conversation events and calculated metrics.

---

## `loader.load_scenario`
Loads a scenario from a JSON or AES YAML file.

```python
from eval_runner import loader
scenario = loader.load_scenario("industries/telecom/scenarios/fraud_1.json")
```

**v1.1 Features:**
- **Relative Path Resolution**: Automatically resolves `dataset.path` relative to the scenario file.

---

## `metrics.calculate_state_correctness`
Verifies parity between expected and actual sandbox state.

**Parameters:**
- `expected`: Dictionary of paths and values. Supports **dot-notation** (e.g., `a.b.c`).
- `actual`: The current sandbox state dictionary.

---

## `metrics.calculate_luna_judge_score` (Async)
Calculates a semantic score using an LLM judge.

**Parameters:**
- `criterion`: Success criterion including `threshold` and `required` flag.
- `context`: Evaluation context for the judge.

**v1.1 Features:**
- **Judge Guarding**: Raises `RuntimeError` if `required: true` and the provider is missing.
