# STORY: The Blame Game (Attribution Interpretation)

Welcome Agent, to the board room. We've got a problem. The customer support agent just failed a high-stakes migration.

## 📖 The Conflict
- **The LLM Team**: Says the model is fine, it's the agent's logic.
- **The Agent Team**: Says the logic is sound, but the model misunderstood the instructions.
- **The Board**: Wants to spend **$50,000** to upgrade the model to Gemini Ultra. 💸

## 🏆 Your Task
Check the **Attribution Chart** in `attribution_sample.json`.

1.  **Analyze**: Look at the `model_reasoning` vs. `agent_logic` scores.
2.  **Decide**: Is the failure a **Brain** (Model) issue or a **Body** (Agent) issue?
3.  **Submit**: Recommend the next step for the board.

## 📊 Technical Backdrop
Every evaluation trace is tagged with **Internal Model Probabilities** and **Verification Signatures**. By Comparing the model's confidence in its reasoning with the output accuracy, we can accurately "Attribute" the failure. This prevents wasting enterprise budgets on expensive models when simple code fixes are the answer.

---
*Ready to save the company $50,000? Run the [plot_attribution.py](./plot_attribution.py) next!*
