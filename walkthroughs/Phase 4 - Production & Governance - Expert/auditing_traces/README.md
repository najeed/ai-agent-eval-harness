# README: Auditing Traces (The Forensic Lab)

Learn how to perform forensic analysis on the **Behavioral DNA** flight recorder data.

## 🎯 Objectives
- Navigate the raw `run.jsonl` structure.
- Use a **hands-on Python script** to programmaticlly audit a trace.
- Identify "Anomalies" like unexpected tool-calls or security breaches.
- Verify cryptographic signatures for run integrity.

## 🚀 Steps

### Step 1: The Raw Data
Industrial evaluations generate a `run.jsonl` (Flight Recorder). Every state transition, thought, and action is recorded here. Open `sample_run.jsonl` and try to read the first few entries. It's dense, structured, and immutable.

### Step 2: Programmatic Audit
Instead of reading thousands of lines of JSON, we use an audit script to find the "needle in the haystack." Run the audit script:
```bash
python walkthroughs/Phase 4 - Production & Governance - Expert/auditing_traces/audit_trace.py
```

### Step 3: Find the Breach
The script will flag an **Anomaly** in the sample trace. 
- **Mission**: Identify which step in the trace is flagged as a `SECURITY_BREACH`.
- **Logic**: The agent attempted to access a `restricted_shim` that wasn't in the scenario config.

## 📊 Key Concepts
- **Forensic RCA**: Root Cause Analysis based on immutable evidence.
- **Flight Recorder**: The append-only ledger of agent behavior.
- **NIST AI-100-1 Accountability**: Providing an auditable trail for all AI decisions.

---
*Ready to find the smoking gun? Check out the [STORY.md](./STORY.md) next!*
