# Walkthrough: Beginner Exploration

Welcome! In this first walkthrough, you'll learn how to navigate the MultiAgentEval Catalog and execute your first agentic benchmark.

## 🎯 Objectives
- List all available scenarios in the harness.
- Search for a specific industrial benchmark.
- Execute a single evaluation and view the results.

## 🚀 Step 1: Discover Scenarios
The first thing every user needs to know is what can be tested. Run this command:
```bash
multiagent-eval list
```
You'll see a categorized list of all scenarios in the `industries/` and `scenarios/` directories.

## 🚀 Step 2: Search for Finance
Need to test a specific capability? Use the search filter:
```bash
multiagent-eval list --query finance
```

## 🚀 Step 3: Run Your First Evaluation
Let's run a sample evaluation. If you don't have a live agent running, the harness will use a simulated HTTP adapter.
```bash
multiagent-eval evaluate --path scenarios/telecom/connectivity_check.json
```

## 📊 What Just Happened?
1. **Discovery**: The harness located the scenario JSON.
2. **Execution**: It attempted to call your agent (using a simulator).
3. **Evaluation**: The Judge analyzed the agent's response against the 'Expected Outcome'.
4. **Reporting**: A summary was printed to your console, and a trace was saved in the `runs/` directory.

---
*Ready for more? Proceed to the [Intermediate Pack Installation](../../Phase%202%20-%20Scale%20%26%20Robustness%20-%20Intermediate/pack_installation/README.md) guide.*








