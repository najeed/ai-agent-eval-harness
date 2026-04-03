# README: Industrial CI/CD Gate (The Hard Gate)

Learn how to integrate the evaluation harness into your deployment pipeline using an automated, rule-based "Hard Gate."

## 🎯 Objectives
- Configure a **CI/CD Threshold** (Rho, Accuracy, and Consensus).
- Simulate a **Release Block** when evaluation metrics fall below the "Hard Gate."
- Log a **Deployment Audit** that includes the reason for failure.

## 🚀 Steps

### Step 1: Configure the Sentinel
Look at `cicd_config_rho_0.7.yaml`. It defines the security rules for the release.
- **`required_rho`**: 0.7 (The minimum judge-human correlation).
- **`min_success_rate`**: 0.95 (The minimum passing score).

### Step 2: Run the Release Simulation
This interactive script will simulate a push to production. It will first execute a series of evaluations and then consult the CI/CD gate rules.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/cicd_gate/Step_1_Verify_Bypass.py"
```

### Step 3: Inspect the Audit
Once the gate blocks the release, check the generated **Release Audit**. It will show exactly which baseline (Rho or Accuracy) was violated.

## 📊 Key Concepts
- **Automated Governance**: In industrial DevOps, humans set the policy (via YAML), and the "Sentinel" (the harness) automatically enforces it.
- **Fail-Fast**: By blocking weak agents at the CI/CD gate, we prevent catastrophic failures in the real world.

---
*Ready to guard the gate? Run the [Step_1_Verify_Bypass.py](./Step_1_Verify_Bypass.py) script next!*







