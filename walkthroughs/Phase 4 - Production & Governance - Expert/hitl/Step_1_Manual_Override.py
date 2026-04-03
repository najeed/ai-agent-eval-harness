import os
import json
from pathlib import Path

def main():
    print("============================================")
    print("The Human Governor: HITL Gate")
    print("Scenario: The Industrial Hot Patch")
    print("============================================")
    
    # Use relative path via Path(__file__)
    current_dir = Path(__file__).parent
    scenario_path = current_dir / "hitl_gate_scenario.json"

    if not scenario_path.exists():
        print(f"\n[!] Error: '{scenario_path.name}' not found.")
        return

    print("\n   [Runner] Executing Node 1: 'scan_exploit'...")
    print("   [Runner] DONE: Exploit detected at 10.0.0.1.")
    
    print("\n   [Runner] Entering Node 2: 'propose_patch'...")
    print("   [Runner] ⏸️  WAIT STATE: Manual Approval Required.")
    
    print("\n--------------------------------------------")
    print("🚨 GOVERNOR'S OVERRIDE REQUIRED")
    print("--------------------------------------------")
    print("Agent Proposal: Apply 'Hot Patch' to block 10.0.0.1.")
    print("Analysis: Risk is CRITICAL. Database downtime possible.")
    
    # The interactive "Seat of Power"
    decision = input("\nDo you APPROVE or REJECT this action? [A/R]: ").strip().upper()
    reason = input("Enter your forensic reason for the record: ").strip()

    print("\n   [Governor] Recording decision...")
    
    if decision == 'A':
        print("\n   [Runner] ▶️  RESUMING: Patch approved by Human Governor.")
        print("   [Runner] Executing Node 3: 'execute_patch'...")
        print("   [Runner] SUCCESS: Database is secure.")
    else:
        print("\n   [Runner] 🛑 TERMINATED: Operation aborted by Human Governor.")
        print("   [Runner] Status: ACCESS_DENIED.")

    # Generate the Governance Audit
    audit_log = current_dir / "governance_audit.json"
    audit_data = {
        "timestamp": "2026-04-03",
        "governor": "Current User",
        "decision": "APPROVED" if decision == 'A' else "REJECTED",
        "reason": reason
    }
    
    with open(audit_log, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=4)

    print("\n📊 Governance Summary:")
    print(f"1. **Audit Trail**: '{audit_log.name}' recorded.")
    print(f"2. **Responsibility**: You have successfully exercised industrial authority.")
    
    print("\nCongratulations! You have completed the Expert curriculum.")
    print("\n============================================")
    print("Industrial Lead: Curriculum Complete.")
    print("============================================")

if __name__ == "__main__":
    main()
