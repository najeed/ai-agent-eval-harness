# README: Interpreting Attribution (The Blame Game)

Learn how to decouple LLM "intelligence" from Agent "logic" using industrial attribution charts.

## 🎯 Objectives
- Understand the **Model vs. Agent** attribution model.
- Learn how to read the **Attribution Chart** to identify root causes.
- Make business decisions based on where the failure originates.

## 🚀 Steps

### Step 1: The Attribution Snapshot
Open `attribution_sample.json`. This is a mock result from an evaluation run. It contains a `trustworthiness_vector` and an `attribution` block:
```json
"attribution": {
  "model_reasoning": 0.3,
  "agent_logic": 0.7,
  "tool_reliability": 0.9
}
```
In this scenario, the total failure was primarily caused by the **Model Reasoning** (only 0.3), while the **Agent Logic** (0.7) and **Tool Reliability** (0.9) remained high.

### Step 2: Visualize the Blame
Run the visualization script to render the industrial attribution chart:
```bash
python walkthroughs/Phase 3 - Intelligence & Complexity - Advanced/interpreting_attribution/plot_attribution.py
```

### Step 3: Analysis
Look at the chart. If the **Model** bar is low, you need a better LLM (e.g., upgrade to Gemini 1.5 Pro). If the **Agent** bar is low, you need better prompt engineering or state management.

## 📊 Key Concepts
- **Cognitive Attribution**: Identifying if the LLM misunderstood the task.
- **Systemic Attribution**: Identifying if the agentic glue code or tool definitions are broken.
- **The "Blame" Decoupling**: Crucial for industrial scaling and cost optimization (don't buy a better model if the code is broken).

---
*Ready to stop the finger-pointing? Check out the [STORY.md](./STORY.md) next!*
