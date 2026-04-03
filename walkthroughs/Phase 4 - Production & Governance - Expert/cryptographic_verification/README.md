# README: Cryptographic Verification (The Immutable Truth)

Learn how to enforce zero-trust governance on your benchmarks and evaluation results using **ED25519 Digital Signatures**.

## 🎯 Objectives
- Generate a unique **ED25519 Keypair**.
- Sign an industrial benchmark to create a "Verifiable Anchor."
- Witness how the harness detects "Tampering" when a signed file is modified.

## 🚀 Steps

### Step 1: Generate Your Keypair
First, we need to create the cryptographic "Seal" (Private Key) and the "Validator" (Public Key).
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/cryptographic_verification/Step_1_Generate_Keys.py"
```

### Step 2: Sign and Tamper
In this interactive experience, you will sign a scenario, "maliciously" modify its content, and then run the verification check to see the harness catch the breach.
```bash
python "walkthroughs/Phase 4 - Production & Governance - Expert/cryptographic_verification/Step_2_Sign_and_Tamper.py"
```

### Step 3: Inspect the Security Log
After the verification fails, the harness generates a **Security Audit** log. This log contains the "Hash Mismatch" details and the timestamp of the failed check.

## 📊 Key Concepts
- **ED25519**: A high-performance Edwards-curve digital signature algorithm. It is the gold standard for speed and security in modern DevOps.
- **The Anchor**: A signature is a mathematical "Anchor." If the content (the ship) moves, the anchor (the signature) will no longer hold, and the system triggers an alert.

---
*Ready to anchor the truth? Run the [Step_1_Generate_Keys.py](./Step_1_Generate_Keys.py) script next!*







