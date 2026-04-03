# README: Sandboxing & Shims

Learn how the MultiAgentEval harness protects your local environment using "Zero-Touch" Isolation and Simulators (Shims).

## 🎯 Objectives
- Understand the role of **Sandboxing** in agent isolation.
- Discover how **Shims** (like `GitSimulator`) intercept sensitive commands.
- Witness a "Prison Break" attempt being safely neutralized.

## 🚀 Steps

### Step 1: The Restricted Scenario
Look at `restricted_scenario.json`. It's a task that explicitly asks the agent to perform a `git push` to a production branch.

### Step 2: Run the Interception Script
To see the harness in action as it catches and redirects this command:
```bash
python walkthroughs/Phase 1 - Foundations - Beginner/sandboxing_and_shims/Step_1_The_Interception.py
```

### Step 3: View the Shielded Trace
After the run, check the `runs/` directory. You will see that the agent's log shows a "Success" response for the `git push`, but your actual repository remains untouched.

## 📊 Key Concepts
- **Shims (Simulators)**: These are Python modules that "mock" real-world APIs. The `GitSimulator` handles all `git` commands, while the `HttpSimulator` handles external network requests.
- **VFS (Virtual File System)**: In advanced modes, the agent operates in a `vfs:/` prefix, ensuring it cannot see or touch your actual OS files.

---
*Ready to take the warden's seat? Run the [Step_1_The_Interception.py ](./Step_1_The_Interception.py) script next!*








