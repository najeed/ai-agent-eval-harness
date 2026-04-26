# README: Industrial Data Extraction (The Ground Truth)

Learn how to harness the **Dataproc Engine** to extract gold-standard industrial data for your evaluation world-states.

## 🎯 Objectives
- Understand the role of **Industrial Providers** (USDA, FCC, WorldBank, etc.).
- Use the `dataproc` CLI to fetch live sector data.
- Validate data against industrial schemas (StandardSchema).
- Integrate extracted data into digital twin simulators.

## 🚀 Steps

### Step 1: Industrial Sectors
The AgentV platform includes specialized providers for over 15 industrial sectors, including Finance, Healthcare, Agriculture, Telecom, and Energy.

### Step 2: Extracting Real-World Data
Let's extract live agricultural data. This ensures your agent is being evaluated against real-world constraints, not just synthetic noise.
```bash
python -m dataproc_engine.cli.main extract --industry agriculture --format jsonl --target-dir industries/agriculture/datasets
```

### Step 3: Schema Validation
Industrial data must be reliable. The `dataproc_engine` automatically validates extracted data against the **StandardSchema**, ensuring fields like `entity_name`, `revenue`, or `timestamp` are present and correctly typed.

### Step 4: Populating Simulators
Once you have your "Ground Truth" data, you can point your simulators (like the CRM or Finance shim) to these JSON files in your scenario configuration:
```json
"config": {
  "shims": {
    "finance": { "input_uri": "./agriculture_data.json" }
  }
}
```

## 📊 Key Concepts
- **Gold-Standard Extraction**: Moving beyond "synthetic data" by grounding evaluations in authenticated industrial sources.
- **Cross-Sector Correlation**: Using the `DataCorrelator` to link disparate datasets (e.g., matching Energy prices with Manufacturing output).
- **Deterministic Drift**: By using real data, you can measure how an agent's performance drifts when the "Ground Truth" shifts (e.g., during a market surge).

---
*Ready to ground your evaluations in reality? Check out the [STORY.md](./STORY.md) next!*
