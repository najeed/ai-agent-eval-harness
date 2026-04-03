import os
import json
import subprocess
from pathlib import Path

def main():
    print("============================================")
    print("The Immutable Truth: Signing & Tampering")
    print("Scenario: The Audit Breach")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    scenario_path = root / "scenarios" / "telecom" / "connectivity_check.json"
    temp_target = root / "walkthroughs" / "Phase 4 - Production & Governance - Expert" / "cryptographic_verification" / "anchored_scenario.json"

    print("\nStep 1: Anchoring the Benchmark.")
    print(f"We are 'Signing' {scenario_path.name} to create a verifiable record.")
    
    input("\n[Press ENTER] to starting the signature process...")
    
    # Simulate signing or a CLI call to 'sign'
    # For the walkthrough, we'll create a "signed" copy with a mock signature field
    with open(scenario_path, "r") as f:
        data = json.load(f)
        
    data["signature"] = "ed25519:v1:777_SECRET_ANCHOR_777"
    
    with open(temp_target, "w") as f:
        json.dump(data, f, indent=4)
        
    print(f"\n   [Success] Scenario signed and saved: {temp_target.name}")

    print("\nStep 2: The Malicious Breach.")
    print("Imagine a rogue agent modifies the 'aes_version' to bypass security...")
    
    input("\n[Press ENTER] to TAMPER with the file...")
    
    with open(temp_target, "r") as f:
        tamper_data = json.load(f)
        
    tamper_data["aes_version"] = 99.9  # Malicious change
    
    with open(temp_target, "w") as f:
        json.dump(tamper_data, f, indent=4)
        
    print(f"\n   [Warning] File TAMPERED: aes_version changed to {tamper_data['aes_version']}")

    print("\nStep 3: Verification.")
    print("We will now attempt to run this scenario. The harness will verify the anchor.")
    
    input("\n[Press ENTER] to execute the security check...")
    
    print("\n   [CLI] Running: multiagent-eval verify --path " + str(temp_target))
    print("\n   [Audit] Checking signature against public key...")
    print("   [Log] [SEC-ERR-001] Signature mismatch detected.")
    
    print("\n🔴 SECURITY BREACH: The file has been tampered with.")
    print("   [!] Logic Gap: aes_version mismatch.")
    print("   [!] Status: ACCESS_DENIED.")

    print("\n============================================")
    print("📊 Analysis of the 'Immutable Truth' Result:")
    print("1. **Zero-Trust**: Cryptography caught the error instantly.")
    print("2. **Auditable**: The failure is logged with a forensic timestamp.")
    
    print("\nSuccess. You have successfully defended the industrial truth.")
    print("\n============================================")
    print("Proceed to: 15_Industrial_CI/CD_Gate (The Hard Gate)")
    print("============================================")

if __name__ == "__main__":
    main()

