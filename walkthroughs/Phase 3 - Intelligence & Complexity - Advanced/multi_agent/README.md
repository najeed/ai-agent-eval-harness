# README: Multi-Agent Interactions (The Silent Swarm)

Learn how to evaluate complex, multi-turn interactions where multiple agents (e.g., a **Researcher** and a **Writer**) must coordinate to solve an industrial task.

## 🎯 Objectives
- Understand the difference between a single-agent and a multi-agent scenario.
- Discover how "State" is passed from one agentic node to another.
- Witness the coordination of a Researcher, Writer, and Auditor in a single benchmark.

## 🚀 Steps

### Step 1: The Multi-Agent Scenario
Look at `multi_agent_scenario.json`. You'll notice it defines three distinct "Nodes" with their own `node_id` and `expected_outcome`.
- **Node A (Researcher)**: Finds the target data.
- **Node B (Writer)**: Transforms the data into a report.
- **Node C (Auditor)**: Verifies the report's accuracy.

### Step 2: Run the Team Evaluation
This script will execute the three-node interaction and provide a "Coordination Audit" on the resulting trace.
```bash
python walkthroughs/Phase 3 - Intelligence & Complexity - Advanced/multi_agent/Step_1_Evaluate_Team.py
```

### Step 3: Audit the Hand-off
Once the run is complete, the script will highlight how the state was modified by each agent and identify if any "Logic Gaps" were introduced during the hand-off.

## 📊 Key Concepts
- **Interaction Complexity**: In industrial settings, agents rarely work alone. Measuring the "Baton Pass" between roles is as important as measuring individual performance.
- **State Persistence**: The harness ensures that memory and context are preserved across the entire DAG (Directed Acyclic Graph) of the interaction.

---
*Ready to coordinate the swarm? Run the [Step_1_Evaluate_Team.py](./Step_1_Evaluate_Team.py) script next!*








