# Module 12: The CI/CD Hard Gate

> [!NOTE]
> **SIMULATION RATIONALE**: This module uses simulated evaluation metrics (e.g., threshold bypasses) to demonstrate the 'Hard Gate' logic without requiring a live Jenkins/GitHub Actions runner. In production, these metrics are derived from real evaluations.

This module demonstrates how to use the evaluation harness as a "quality gate" in a CI/CD pipeline.

## 🎯 Objectives
- Configure a **CI/CD Threshold** (Rho, Accuracy, and Consensus).
- Simulate a **Release Block** when evaluation metrics fall below the "Hard Gate."

## 🛠️ Step-by-Step Instructions

### Step 1: Configure the Gate Rules
Open `walkthroughs/Phase 4 - Production & Governance - Expert/cicd_gate/Step_1_Verify_Bypass.py` and observe the following threshold:
- **`min_success_rate`**: 0.95 (The minimum passing score).

### Step 2: Run the Release Simulation
This interactive script will simulate a push to production. It will first execute a series of evaluations and then consult the CI/CD gate rules.

```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/cicd_gate/Step_1_Verify_Bypass.py"
```

## 📋 Expected Output
If the metrics are below 0.95, you will see a `DANGER: Gated Release Blocked` error. This prevents the "drifts" we identified in the previous modules from reaching the customer.
