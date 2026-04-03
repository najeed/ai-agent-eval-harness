import os
import yaml
import subprocess
from pathlib import Path

def main():
    print("============================================")
    print("The Hard Gate: Industrial CI/CD Sentinel")
    print("Scenario: Release Compliance Check")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    config_path = root / "walkthroughs" / "Phase 4 - Production & Governance - Expert" / "cicd_gate" / "cicd_config_rho_0.7.yaml"

    print("\nStep 1: Inspecting the Sentinel Policy.")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    print(f"Policy: Required Rho >= {config['gate_rules'][0]['value']}.")
    
    print("\nStep 2: Simulating the Evaluation Run.")
    print("The agent is being benchmarked across 100 industrial scenarios...")
    
    input("\n[Press ENTER] to starting the release cycle...")
    
    # Simulated metrics (purposefully low for the walkthrough)
    current_rho = 0.64
    current_score = 0.92
    
    print(f"\n   [Evaluation] Spearman's Rho: {current_rho} (FAILED)")
    print(f"   [Evaluation] Mean Score: {current_score} (FAILED)")
    
    print("\nStep 3: Consult the Hard Gate.")
    input("\n[Press ENTER] to see the Sentinel's decision...")
    
    print("\n   [Sentinel] 🛑 DEPLOYMENT_BLOCKED: Policy Violation [SEC-RHO-LT-0.7]")
    print("   [Log] Rejecting release candidate 'v2.4.1-ULTRA'. Reason: Low correlation.")
    
    # Generate the Audit log
    audit_log = root / "walkthroughs" / "Phase 4 - Production & Governance - Expert" / "cicd_gate" / "release_audit.json"
    with open(audit_log, "w") as f:
        f.write('{"timestamp": "2026-04-03", "status": "REJECTED", "violation": "spearman_rho_low"}')

    print("\n📊 Release Summary:")
    print(f"1. **Status**: REJECTED")
    print(f"2. **Audit Trail**: {audit_log.name}")
    print(f"3. **Refine**: Recommendation: Improve reasoning before re-release.")

    print("\nSuccess. The Sentinel has successfully defended production.")
    print("\n============================================")
    print("Proceed to: 16_Luna_Judge (The Consensus of Giants)")
    print("============================================")

if __name__ == "__main__":
    main()

