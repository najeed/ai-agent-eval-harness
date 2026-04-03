# README: Native Adapters 

Learn how to connect the evaluation harness to different agentic endpoints using the built-in adapter framework.

## 🎯 Objectives
- Understand the difference between `http`, `socket`, and `local` adapters.
- Modify `.env` to change the agent endpoint.
- Evaluate a local Python script using the `local` adapter.

## 🚀 Steps

### Step 1: The Config File
The harness looks at `.env` for its current connection settings.
- **`AGENT_API_URL`**: The endpoint (URL or Local Path).
- **`ADAPTER_TYPE`**: (Inferred from the URL scheme).

### Step 2: The Local Switch
To evaluate a script residing directly in this repository, we use the `local` adapter. Perform this by running:
```bash
python walkthroughs/Phase 1 - Foundations - Beginner/adapters/Step_1_Configure_Adapters.py
```

### Step 3: Run the Local Evaluation
Once configured, execute a scenario against our `local_agent_shim.py` mock.
```bash
multiagent-eval evaluate --path scenarios/telecom/connectivity_check.json
```

## 📊 Key Concepts
- **Shimming**: The `local` adapter "shims" your Python script, allowing it to respond to evaluation requests without needing a web server.
- **Protocol Agnosticism**: Most scenarios are written without knowing which adapter will run them, ensuring high portability across environments.

---
*Ready to build the bridge? Run the [Step_1_Configure_Adapters.py](./Step_1_Configure_Adapters.py) script next!*








