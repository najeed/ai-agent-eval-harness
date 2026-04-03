# README: Luna-Judge & IJA Protocol (The Consensus of Giants)

Learn how to orchestrate high-reliability evaluations using a council of industrial judges and the **IJA (Industrial Judge Agreement)** protocol.

## 🎯 Objectives
- Configure a **Triple-Judge Council** (Luna-1, Luna-2, Luna-3).
- Understand the **IJA Protocol** categories for consensus.
- Execute a multi-judge evaluation and audit the final decision.

## 🚀 Steps

### Step 1: The IJA Protocol
Look at `IJA_protocol_v1_industrial.json`. It defines the weights and roles for each judge in the council.
- **Luna-1**: High weight on "Reasoning."
- **Luna-2**: Heavy penalty for "Constraint Violations."
- **Luna-3**: Final tie-breaker for "Compliance."

### Step 2: Run the Consensus Evaluation
This interactive script will execute a series of evaluations where the judges' opinions differ, and the IJA protocol must resolve the conflict.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/luna_ija/Step_1_Run_IJA_Consensus.py"
```

### Step 3: Inspect the Consensus Audit
After the run, check the **Consensus Audit**. You'll see the individual votes, the reasoning for each, and the final "Blended Score" that determined the outcome.

## 📊 Key Concepts
- **Consensus of Giants**: In high-stakes industries (Finance, Energy), relying on a single LLM model is a risk. A council of judges provides architectural redundancy.
- **Monotonic Agreement**: The IJA Protocol ensures that as the number of judges increases, the reliability of the "Truth" converge.

---
*Ready to summon the giants? Run the [Step_1_Run_IJA_Consensus.py](./Step_1_Run_IJA_Consensus.py) script next!*







