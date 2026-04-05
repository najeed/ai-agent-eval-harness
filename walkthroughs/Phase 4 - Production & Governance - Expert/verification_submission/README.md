# README: Verification & Scoring (The Trust Anchor)

Learn how to perform final verification and formally submit your trustworthiness scores to the **Trust Anchor**.

## 🎯 Objectives
- Conduct a final **NIST AI-100-1 Alignment** check.
- Verify cryptographic signatures (`ED25519`) of the run results.
- Formally **submit the score** to the industrial trust registry.

## 🚀 Steps

### Step 1: The Final Gate
Before a score is "official," it must pass the **Verification Gate**. This is an automated set of checks that verify the run was not modified and was conducted in a hardened environment.

### Step 2: Submit the Score
Run the submission script to simulate the final industrial certification:
```bash
python walkthroughs/Phase 4 - Production & Governance - Expert/verification_submission/submit_score.py
```

### Step 3: Certification
The script will output a **Verification Certificate (VC)**. This is your non-repudiable proof of alignment with industrial 2026 standards.

## 📊 Key Concepts
- **Trust Anchor**: The central authority that validates and stores evaluation certificates.
- **ED25519 Signatures**: A cryptographically secure, asymmetric signature that binds a set of scores to a specific evaluation run.
- **NIST-100 Accountability**: Formal, signed proof of trustworthiness.

---
*Ready to make it official? Run the [submit_score.py](./submit_score.py) next!*
