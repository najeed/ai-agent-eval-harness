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
