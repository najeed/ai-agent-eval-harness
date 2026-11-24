# README: Batch Evaluation (The Concurrent Blitz)

Learn how to manage high-volume, multi-protocol evaluations at industrial scale.

## 🎯 Objectives
- Run a large-scale evaluation across **HTTP, Socket, and Local** protocols.
- Configure execution paths to evaluate multiple industrial scenarios.
- Understand the role of `attempts` and `retry` for flaky connections.

## 🚀 Steps

### Step 1: The Multi-Protocol Manifest
Look at `mixed_protocol_manifest.json`. You'll notice it references three different agent endpoints.
- **`http://localhost:5001/execute_task`** (Cloud Fleet)
- **`local://walkthroughs/Phase 1 - Foundations - Beginner/adapters/local_agent_shim.py`** (Secure Fleet)

### Step 2: Run the Stress Test
To execute trials across these scenarios:
```bash
python "walkthroughs/Phase 2 - Scale & Robustness - Intermediate/batch_evaluation/Step_1_Stress_Test.py"
```

### Step 3: Batch Evaluation Execution
While the evaluation is running, the harness executes through the scenario dataset with automated retry logic and consolidated reporting.

## 📊 Key Concepts
- **Batch Evaluation**: The harness evaluates scenario datasets via `agentv evaluate --path <dir>`.
- **Retry Logic**: Industrial environments are messy. The `attempts` parameter ensures that transient network failures don't poison your results.

---
*Ready to lead the Blitz? Run the [Step_1_Stress_Test.py](./Step_1_Stress_Test.py) script next!*








