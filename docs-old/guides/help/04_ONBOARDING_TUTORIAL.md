# Onboarding Tutorial — MultiAgentEval

Welcome to the harness! This tutorial walks a first-time user (e.g., a Product Manager or Engineering first-timer) through a complete evaluation workflow with real commands and expected outputs.

> 🎯 Goal: Get from zero to a full evaluation run, inspect the results, and understand where to look next.

---

## 👤 Persona: New Evaluator (Product Manager / QA)

**You** are responsible for validating whether an agent behaves correctly for a business scenario. You don’t need to know the internal code; you should be able to:

- Run an evaluation end-to-end
- Understand the key outputs (reports + traces)
- Make a small update to a scenario and re-run

---

## 1 Setup (First Time)

### ✅ Step 1: Clone & Install

Run:

```bash
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness
python -m venv .venv
# Activate the venv (macOS/Linux)
source .venv/bin/activate
# Activate the venv (Windows PowerShell)
# .\.venv\Scripts\Activate.ps1

python -m pip install -e .
python -m pip install -r requirements.txt
```

> ```text
> Successfully installed multi-agent-eval-<version> ...
> ```

### ✅ Step 2: Verify the CLI is available

Run:

```bash
multiagent-eval --help
```

> ✅ Expected output snippet:
>
> ```text
> usage: multiagent-eval [-h] {evaluate,aes,spec-to-eval,import-drift,run,replay,mutate,list,lint} ...
> 
> MultiAgentEval (OpenCore)
> ```

### ✅ Step 3: Explore the Scenario Catalog

Before running an evaluation, discover what's available:

```bash
# List all telecom scenarios
multiagent-eval list --search "telecom"
```

> ✅ Expected output: A table of matching scenarios with IDs and titles.

---

## 2 Run a Quick Evaluation (First Smoke Test)

### ✅ Step 1: Pick a built-in industry scenario

The harness includes industry scenarios under `industries/`. You can use the `list` command above or browse the file system.

### ✅ Step 2: Run the evaluation

```bash
multiagent-eval evaluate --path industries/telecom --export
```

---

## 3 Add your own industry / scenario

Instead of manually typing out JSON, the easiest way to start a new industry benchmark is the `init` command.

1. Scaffold the environment:

```bash
multiagent-eval init --dir industries/retail --industry retail
```

2. Run the newly generated scenario:

```bash
multiagent-eval run --scenario industries/retail/scenarios/starter_scenario.json
```

---

## 4 Validate Scenario Quality

Before sharing or running complex benchmarks, ensure your scenarios meet the AES standard:

```bash
multiagent-eval lint --path industries/retail/scenarios/starter_scenario.json
```

---

## 5 Inspect the Output

### ✅ Replay the run trace

```bash
multiagent-eval replay --path runs/run.jsonl
```

### ✅ View in the Visual Dashboard

```bash
multiagent-eval console
```

Inspect results natively using the **Visual Debugger**. The suite provides a unified hub for the entire lifecycle:
- **Scenario Editor**: Design and save scenarios directly to the industry libraries.
- **Background Runner**: Trigger evaluations and monitor them via the UI.
- **Visual DNA Debugger**: Live trajectory playback, state inspection, and trace export.
- **Search**: Use the sidebar to search for scenarios by title or tags.
- **Quality Badges**: Look for the "Lint Score" on each scenario. Scenarios with a score of **90+** are considered high-fidelity benchmarks.
- **Documentation Drawer**: Click the "API Reference" icon to see these guides directly within the app.

---

## 6 Next Steps

- ✅ Read the **User Manual** (`docs/guides/help/02_USER_MANUAL.md`).
- 🧠 Read the **Developer Guide** (`docs/guides/help/03_DEVELOPER_GUIDE.md`) for adapters and plugins.
- 📂 **Path Decoupling (v1.1+)**: You don't have to keep scenarios in `industries/`. You can now run `multiagent-eval evaluate --path <any_folder>` and it will work out of the box!

Happy evaluating!
