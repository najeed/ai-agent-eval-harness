# README: Trace Importer (The Time Traveler's Log)

Learn how to bridge the gap between production logs and the evaluation harness by capturing and replaying real-world agentic failures.

## 🎯 Objectives
- Simulate a **Production Capture** event.
- Transform a raw, messy production JSON log into a structured AES scenario using `import-drift`.
- Perform a "Replay Verification" to confirm the drift has been codified.

## 🚀 Steps

### Step 1: Capture the Production Log
Before we can import the drift, we need to "extract" the log from our simulated production endpoint.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/trace_importer/Generate_Prod_Log.py"
```

### Step 2: Run the Import Script
This script will call the `import-drift` command to parse the newly captured `production_raw.log` and generate a valid AES JSON scenario.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/trace_importer/Step_1_Import_to_Scenario.py"
```

### Step 3: Replay & Verify
Once the new scenario is generated, look at the resulting `imported_incident_001.json`. You can now run this through the `evaluate` command to isolate the exact moment of failure.

## 📊 Key Concepts
- **Drift Capture**: Capture the value of real-world failures by codifying them into your regression suite.
- **Trace Parity**: Ensuring that the imported scenario is a 1:1 replica of the original production event.

---
*Ready to replay the incident? Run the [Generate_Prod_Log.py](./Generate_Prod_Log.py) script next!*







