import os
import json
import subprocess
from pathlib import Path

def main():
    print("============================================")
    print("The Mirror Consistency: Parity Scanner")
    print("Scenario: Identifying Environment Drift")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    drift_path = root / "walkthroughs" / "Phase 4 - Production & Governance - Expert" / "state_parity" / "registry_drift_sample.json"

    if not drift_path.exists():
        print("\n[!] Error: 'registry_drift_sample.json' not found. Please run 'Generate_Parity_Drift.py' first.")
        return

    with open(drift_path, "r") as f:
        data = json.load(f)

    print("\nWe are comparing the 'Golden' Production State against the 'Staging' Mirror.")
    print("Any discrepancy in configuration can poison our evaluation results.")
    
    input("\n[Press ENTER] to starting the parity scan...")
    
    print("\n   [Scanner] Hashing environment variables...")
    print("   [Scanner] Verifying library versions...")
    print("   [Scanner] Checking concurrency limits...")
    
    # Analyze the drift
    golden = data["golden"]
    staging = data["staging"]
    
    diffs = []
    for k, v in golden.items():
        if staging[k] != v:
            diffs.append(f"Field '{k}': Expected '{v}', Found '{staging[k]}'")

    print("\n📊 Mirror Consistency Report:")
    if diffs:
        print(f"⚠️  DRIFT DETECTED: {len(diffs)} inconsistencies found.")
        for diff in diffs:
            print(f" - {diff}")
        print("\n[Action Required] Reset staging mirror to '1.2.3' and lock concurrency to 50.")
    else:
        print("✅ MIRROR CONSISTENT: Parity factor is 100%.")

    print("\nSuccess. You have identified the distortion in the mirror.")
    print("\n============================================")
    print("Proceed to: 14_Cryptographic_Verification (The Immutable Truth)")
    print("============================================")

if __name__ == "__main__":
    main()

