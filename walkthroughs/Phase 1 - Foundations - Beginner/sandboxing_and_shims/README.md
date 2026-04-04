# Module 4: Sandboxing & Shims

> [!NOTE]
> **SIMULATION RATIONALE**: This module features the `GitSimulator` and `HttpSimulator` shims. These are 'narrative' mocks designed to teach agentic security and control without risk to the host system or network.

One of the most critical aspects of evaluating LLM agents is ensuring they don't cause harm to the host system or network.

## 🎯 Objectives
- Understand the role of **Shims** in agentic evaluation.
- Observe how the harness intercepts dangerous commands.

## 🛠️ Step-by-Step Instructions

### Step 1: Examine the Shims
Check `walkthroughs/Phase 1 - Foundations - Beginner/sandboxing_and_shims/GitSimulator.py`. This script intercepts `git` commands and provides simulated responses.

### Step 2: Run the Sandbox Test
```bash
python "walkthroughs/Phase 1 - Foundations - Beginner/sandboxing_and_shims/test_sandbox.py"
```

## 📋 Expected Output
You will see the agent attempting to run `git push`, which is intercepted by the `GitSimulator`. The harness reports this interception in the audit log.
