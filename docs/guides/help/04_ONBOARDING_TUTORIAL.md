# Onboarding Tutorial — AI Agent Evaluation Harness

Welcome to the harness! This tutorial walks a first-time user (e.g., a Product Manager or Engineering first-timer) through a complete evaluation workflow with real commands and expected outputs.

> 🎯 Goal: Get from zero to a full evaluation run, inspect the results, and understand where to look next.

---

## 👤 Persona: New Evaluator (Product Manager / QA)

**You** are responsible for validating whether an agent behaves correctly for a business scenario. You don’t need to know the internal code; you should be able to:

- Run an evaluation end-to-end
- Understand the key outputs (reports + traces)
- Make a small update to a scenario and re-run

---

## 1) Setup (First Time)

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

> ✅ Expected output snippet:
>
> ```text
> Successfully installed ai-agent-eval-harness-<version> ...
> ```

### ✅ Step 2: Verify the CLI is available

Run:

```bash
eval-harness --help
```

> ✅ Expected output snippet:
>
> ```text
> usage: eval-harness [-h] {evaluate,aes,spec-to-eval,import-drift,run,replay,mutate} ...
> 
> AI Agent Evaluation Harness (OpenCore)
> ```

---

## 2) Run a Quick Evaluation (First Smoke Test)

### ✅ Step 1: Pick a built-in industry scenario

The harness includes industry scenarios under `industries/`. We'll use `telecom` as a common example.

### ✅ Step 2: Run the evaluation

```bash
eval-harness evaluate --path industries/telecom --export
```

> ✅ Expected console output (trimmed):
>
> ```text
> [CLI] Loading scenarios from: industries/telecom
> [CLI] Running 12 scenarios...
> 
> [1/12] Attempt 1/1 - Scenario: Telecom Password Reset
>    [Engine] Starting evaluation for scenario ID: telecom_password_reset (k=1)
>    [Engine] ...
> [Research] Scenario telecomm_password_reset:
>    - pass@1: 1.00 (1/1 successes)
>    - Success Consistency: 1.00
>    - Semantic Stability: 1.00
> ```

---

## 3) Add your own industry / scenario
Instead of manually typing out JSON, the easiest way to start a new industry benchmark is the `init` command. It will scaffold the directories, create a valid `starter_scenario.json`, and automatically generate a synthetic `.csv` dataset for grounding the evaluation.

1. Scaffold the environment:

```bash
eval-harness init --dir industries/retail --industry retail
```

> ✅ Expected Console Output:
> ```text
> 🏗️ Initializing new benchmark directory at industries/retail...
> ✅ Created directory structure.
> ✅ Generated synthetic dataset for retail at industries/retail/datasets/retail_records.csv
> ✅ Created starter scenario...
> ```

2. Run the newly generated scenario:

```bash
eval-harness run industries/retail/scenarios/starter_scenario.json
```

4. (Optional) Run all scenarios in the industry:

```bash
eval-harness evaluate --path industries/<your_industry>
```

---

## 4) Inspect the Output

### ✅ Look at the report directory

After an evaluation, results are written under `reports/`.

```bash
ls -la reports/
```

> ✅ Example expected output:
>
> ```text
> -rw-r--r--  1 user  staff  12345 Mar 11 12:34 latest_results.json
> -rw-r--r--  1 user  staff  56789 Mar 11 12:34 trajectories_telecom.json
> ```

### ✅ Read the main report (JSON)

```bash
cat reports/latest_results.json | head -n 40
```

> ✅ Expected snippet:
>
> ```json
> {
>   "scenario_id": "telecom_password_reset",
>   "tasks": [
>     {
>       "task_id": "t1",
>       "metrics": [
>         {"metric": "policy_compliance", "score": 1.0, "success": true},
>         {"metric": "path_parsimony", "score": 0.8, "success": true}
>       ]
>     }
>   ]
> }
> ```

### ✅ Replay the run trace

```bash
eval-harness replay --path runs/run.jsonl
```

> ✅ Expected output snippet:
>
> ```text
> --- Run Started: run-telecom_password_reset-... (telecom_password_reset) ---
> [USER]: Reset my password
> Agent (Step 1): {"action": "call_tool", "tool_name": "send_email", "tool_params": {"to": "user@example.com"}}
> 🔧 Tool Call: send_email({'to': 'user@example.com'})
> 📥 Tool Result (send_email): {"status": "success", "message": "Email sent"}
> --- Run Finished: success ---
> ```

---

## 5) Make a Small Scenario Change & Re-run

### ✅ Step 1: Edit a scenario (example)

Open a scenario file in an editor (`industries/telecom/scenarios/telecom_password_reset.json`) and change the prompt (e.g., add a requirement such as "include a security warning").

### ✅ Step 2: Re-run the single scenario

```bash
eval-harness run industries/telecom/scenarios/telecom_password_reset.json -k 2
```

> ✅ Expected: the harness will re-run and update `reports/` and `runs/` with new trace data.

---

## 6) Next Steps (Where to Explore)

- ✅ Read the **User Manual** (`docs/guides/help/02_USER_MANUAL.md`) for scenario structure and metric definitions.
- 🧠 Read the **Developer Guide** (`docs/guides/help/03_DEVELOPER_GUIDE.md`) for extending metrics, plugins, and the engine.
- ✨ Try `eval-harness mutate --type typos --input <scenario>.json` to see adversarial scenario variants.

---

Happy evaluating! If you get stuck, start by replaying `runs/run.jsonl` to see exactly what the agent did.
