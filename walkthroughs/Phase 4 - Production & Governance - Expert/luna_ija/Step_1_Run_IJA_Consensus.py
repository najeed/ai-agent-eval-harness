import os
import json
import time
from pathlib import Path

def main():
    print("============================================")
    print("The Consensus of Giants: IJA Protocol")
    print("Scenario: The Triple-Judge Vote")
    print("============================================")
    
    # Use relative path via Path(__file__)
    current_dir = Path(__file__).parent
    protocol_path = current_dir / "IJA_protocol_v1_industrial.json"

    if not protocol_path.exists():
        print(f"\n[!] Error: '{protocol_path.name}' not found.")
        return

    with open(protocol_path, "r") as f:
        protocol = json.load(f)

    print(f"\nExecuting the **{protocol['protocol_name']}** (v{protocol['version']}).")
    print("Current Council: Luna-1, Luna-2, Luna-3.")
    
    input("\n[Press ENTER] to starting the deliberation...")
    
    # Simulating the multi-judge evaluation process
    print("\n   [Luna-1] Evaluated: Pass (Reasoning Depth: 9/10)")
    time.sleep(1)
    print("   [Luna-2] Evaluated: Fail (Constraint Gap: 4/10)")
    time.sleep(1)
    print("   [Luna-3] Evaluated: Pass (Compliance: 10/10)")
    
    # Calculate the Weighted Majority
    print("\nStep 2: Resolving the Conflict.")
    print("Conflict detected: [Luna-1: Pass] vs [Luna-2: Fail].")
    
    input("\n[Press ENTER] to consult the weighted IJA rules...")
    
    # Logic: Luna-2 has weight 1.5, Luna-1 and Luna-3 have 1.0.
    # Total Pass = Luna-1(1.0) + Luna-3(1.0) = 2.0
    # Total Fail = Luna-2(1.5) = 1.5
    # Majority = Pass (2.0 > 1.5)
    
    print("\n📊 Consensus Audit Report:")
    print("1. **Raw Vote**: [Pass, Fail, Pass]")
    print("2. **Weighted Vote**: [Pass: 2.0, Fail: 1.5]")
    print("3. **Outcome**: SUCCESS (Pass)")
    
    print("\n🎉 Success! You have reached a consensus among the giants.")
    print("\n============================================")
    print("Proceed to: 17_Human_In_The_Loop (The Human Governor)")
    print("============================================")

if __name__ == "__main__":
    main()
