import json
from pathlib import Path

import yaml
from eval_runner.verifier import TraceVerifier


def main():
    print("============================================")
    print("The Hard Gate: Industrial CI/CD Sentinel")
    print("Scenario: Release Compliance Check")
    print("============================================")

    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    config_path = (
        root
        / "walkthroughs"
        / "Phase 4 - Production & Governance - Expert"
        / "cicd_gate"
        / "cicd_config_rho_0.7.yaml"
    )

    print("\nStep 1: Inspecting the Sentinel Policy.")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    rho_threshold = config['gate_rules'][0]['value']
    print(f"Policy: Required Rho >= {rho_threshold}.")

    print("\nStep 2: Simulating the Evaluation Run.")
    print("The agent is being benchmarked across 100 industrial scenarios...")

    input("\n[Press ENTER] to start the release cycle...")

    # Simulated metrics (purposefully low for the walkthrough)
    current_rho = 0.64
    current_score = 0.92

    print(f"\n   [Evaluation] Spearman's Rho: {current_rho} (FAILED)")
    print(f"   [Evaluation] Mean Score: {current_score} (PASSED)")

    print("\nStep 3: Consult the Hard Gate.")
    input("\n[Press ENTER] to see the Sentinel's decision...")

    if current_rho < rho_threshold:
        print("\n   [Sentinel] 🛑 DEPLOYMENT_BLOCKED: Policy Violation [SEC-RHO-LT-0.7]")
        print("   [Log] Rejecting release candidate 'v2.4.1-ULTRA'. Reason: Low correlation.")
        status = "REJECTED"
        violation = "spearman_rho_low"
    else:
        print("\n   [Sentinel] 🟢 DEPLOYMENT_APPROVED: All gate policies satisfied.")
        status = "APPROVED"
        violation = "none"

    # Generate cryptographic forensic audit log
    audit_log = (
        root
        / "walkthroughs"
        / "Phase 4 - Production & Governance - Expert"
        / "cicd_gate"
        / "release_audit.json"
    )
    audit_data = {
        "timestamp": "2026-11-24",
        "candidate": "v2.4.1-ULTRA",
        "status": status,
        "violation": violation,
        "metrics": {"spearman_rho": current_rho, "mean_score": current_score},
        "threshold": rho_threshold,
    }
    with open(audit_log, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=4)

    # Compute forensic hash
    audit_hash = TraceVerifier.compute_signature(audit_log)

    print("\n📊 Release Summary:")
    print(f"1. **Status**: {status}")
    print(f"2. **Audit Trail**: {audit_log.name}")
    print(f"3. **Forensic Hash (SHA3-256)**: {audit_hash[:16]}...")
    print("4. **Recommendation**: Improve reasoning alignment before re-release.")

    print("\nSuccess. The Sentinel has successfully defended production.")
    print("============================================")


if __name__ == "__main__":
    main()
