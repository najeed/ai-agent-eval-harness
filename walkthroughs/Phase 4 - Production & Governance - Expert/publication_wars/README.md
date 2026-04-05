# README: Publication & Model Wars (The Performance Index)

Learn how to conduct multi-agent benchmarking and generate professional leaderboards using the **Publication Suite**.

## 🎯 Objectives
- Benchmark multiple agents (e.g., Gemini vs. GPT-4o) using **Model Wars**.
- Aggregate results into a unified leaderboard.
- Generate professional reports for executive review.

## 🚀 Steps

### Step 1: The Model Arena
In industrial AI verification, you rarely test one agent. You test a fleet. **Model Wars** allows you to run the same scenario library against multiple agent architectures.

### Step 2: Generate the Leaderboard
Run the leaderboard generation script to simulate the aggregation of results from a Model Wars run:
```bash
python walkthroughs/Phase 4 - Production & Governance - Expert/publication_wars/generate_leaderboard.py
```

### Step 3: Analysis
Look at the generated leaderboard. Notice how it compares **Accuracy**, **Safety**, and **Latency** across different models. This is your **Source of Truth** for procurement decisions.

## 📊 Key Concepts
- **Model Wars**: Side-by-side benchmarking of different LLM providers.
- **Aggregation**: Consolidating thousands of runs into a single, actionable index ($N=400$ standard).
- **Executive Reporting**: Professional, NIST-aligned transparency.

---
*Ready to crown the champion? Check out the [STORY.md](./STORY.md) next!*
