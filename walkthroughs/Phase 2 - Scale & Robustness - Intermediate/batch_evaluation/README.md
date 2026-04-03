# README: Batch Evaluation (The Concurrent Blitz)

Learn how to manage high-volume, multi-protocol evaluations at industrial scale.

## 🎯 Objectives
- Run a large-scale evaluation across **HTTP, Socket, and Local** protocols.
- Configure `concurrency` to speed up tests by running them in parallel.
- Understand the role of `attempts` and `retry` for flaky connections.

## 🚀 Steps

### Step 1: The Multi-Protocol Manifest
Look at `mixed_protocol_manifest.json`. You'll notice it references three different agent endpoints.
- **`http://localhost:5001/execute_task`** (Cloud Fleet)
- **`local://walkthroughs/Phase 1 - Foundations - Beginner/adapters/local_agent_shim.py`** (Secure Fleet)

### Step 2: Run the Stress Test
To execute fifty trials across these protocols simultaneously:
```bash
python walkthroughs/Phase 2 - Scale & Robustness - Intermediate/batch_evaluation/Step_1_Stress_Test.py
```

### Step 3: Monitor Concurrency
While the "Blitz" is running, notice how the harness spawns multiple evaluation threads. This maximizes your throughput and ensures you don't wait for a slow agent.

## 📊 Key Concepts
- **Concurrency**: The harness uses an asynchronous worker-pool. You can set this via the `--concurrency` CLI flag or in your manifest.
- **Retry Logic**: Industrial environments are messy. The `attempts` parameter ensures that transient network failures don't poison your results.

---
*Ready to lead the Blitz? Run the [Step_1_Stress_Test.py](./Step_1_Stress_Test.py) script next!*








