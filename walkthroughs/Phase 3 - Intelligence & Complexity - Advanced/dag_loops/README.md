# README: DAG Loops & Flow Control (The Recursion Paradox)

Learn how to handle complex, non-linear workflows where an agent's failure or "Logic Gap" triggers a conditional retry or refinement cycle.

## 🎯 Objectives
- Understand **Directed Acyclic Graph (DAG)** cycles in the AES framework.
- Configure `conditional_edges` to trigger a refinement loop.
- Visualize an agent's path through a multi-turn recursion.

## 🚀 Steps

### Step 1: The Looping Scenario
Look at `looping_scenario.json`. You'll notice a special edge:
- **`on_failure` -> `Researcher`**: If the Auditor node fails the consensus check, the flow points back to the Researcher for a "State Refinement" attempt.

### Step 2: Run the Paradox Script
This script will execute the looping benchmark and purposefully fail the first turn to demonstrate the autonomous recovery.
```bash
python walkthroughs/Phase 3 - Intelligence & Complexity - Advanced/dag_loops/Step_1_Flow_Visualization.py
```

### Step 3: Visualize the Path
After the run, the script will generate a **Mermaid.js** graph script. You can paste this into a Mermaid live-editor to see the "Spiral" of recursion.

## 📊 Key Concepts
- **Conditional Edges**: Nodes in a scenario can have multiple egress paths based on `on_completion`, `on_success`, or `on_failure`.
- **Max Loops**: To prevent infinite recursion, the harness supports a `max_loop_count` safety gate at the engine level.

---
*Ready to resolve the paradox? Run the [Step_1_Flow_Visualization.py](./Step_1_Flow_Visualization.py) script next!*








