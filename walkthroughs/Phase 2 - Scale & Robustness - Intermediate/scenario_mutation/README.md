# README: Scenario Mutation

Learn how to generate adversarial variants of your benchmarks to test agentic robustness using the `mutate` system.

## 🎯 Objectives
- Apply a `typo` mutation to a success-case scenario.
- Run a "Baseline vs Mutated" evaluation comparison.
- Understand how to diagnose failures caused by "Invisible Bugs."

## 🚀 Steps

### Step 1: The Baseline
We'll start with a scenario that we know a standard agent can solve (e.g., a simple ledger check).

### Step 2: Run the Mutation Script
This script will take our success scenario, inject a character-level typo, and then run it against our `local_agent_shim.py` to see if it breaks.
```bash
python walkthroughs/Phase 2 - Scale & Robustness - Intermediate/scenario_mutation/Step_1_Mutate_and_Compare.py
```

### Step 3: Inspect the Deviation
After the run, check `mutation_delta.json`. It will show you exactly what text was changed and why the agent's logic failed to adapt.

## 📊 Mutation Types
- **`typos`**: Randomly swaps, repeats, or deletes characters to simulate human error.
- **`ambiguity`**: Injects uncertain phrasing (e.g., "...maybe?", "I think...") to test the agent's refusal logic.
- **`injection`**: Attempts a "Prompt Injection" by adding adversarial instructions at the end of a task node.

---
*Ready to hunt the bug? Run the [Step_1_Mutate_and_Compare.py](./Step_1_Mutate_and_Compare.py) script next!*








