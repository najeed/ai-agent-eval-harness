import json
from pathlib import Path

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner.reference.approval_store import get_default_approval_store


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

    # Initialize live ApprovalStore
    store = get_default_approval_store()
    token = "app_token_hotpatch_001"
    request = ApprovalRequest(
        approval_token=token,
        run_id="scenario_hitl_001",
        action_payload={"action": "block_ip", "ip": "10.0.0.1"},
        prompt="Apply 'Hot Patch' to reconfigure firewall and block 10.0.0.1.",
        required_role="SecurityAdmin",
    )
    store.create_request(request)

    print("\n--------------------------------------------")
    print("🚨 GOVERNOR'S OVERRIDE REQUIRED (Durable Approval Request Created)")
    print("--------------------------------------------")
    print(f"Approval Token: {token}")
    print("Agent Proposal: Apply 'Hot Patch' to block 10.0.0.1.")
    print("Analysis: Risk is CRITICAL. Database downtime possible.")

    # The interactive "Seat of Power"
    decision = input("\nDo you APPROVE or REJECT this action? [A/R]: ").strip().upper()
    reason = input("Enter your forensic reason for the record: ").strip()

    print("\n   [Governor] Recording decision to ApprovalStore...")
    store.resolve_request(
        token,
        decision="APPROVED" if decision == "A" else "REJECTED",
        decision_reason=reason,
        decided_by="HumanGovernor",
    )

    resolved_req = store.get_request(token)
    print(f"   [ApprovalStore] State: {resolved_req.status} | Decision: {resolved_req.decision}")

    if decision == "A":
        print("\n   [Runner] ▶️  RESUMING: Patch approved by Human Governor.")
        print("   [Runner] Executing Node 3: 'execute_patch'...")
        print("   [Runner] SUCCESS: Database is secure.")
    else:
        print("\n   [Runner] 🛑 TERMINATED: Operation aborted by Human Governor.")
        print("   [Runner] Status: ACCESS_DENIED.")

    # Generate the Governance Audit
    audit_log = current_dir / "governance_audit.json"
    audit_data = {
        "timestamp": "2026-11-24",
        "governor": "HumanGovernor",
        "approval_token": token,
        "decision": resolved_req.decision,
        "reason": reason,
        "store_status": resolved_req.status,
    }

    with open(audit_log, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=4)

    print("\n📊 Governance Summary:")
    print(f"1. **Audit Trail**: '{audit_log.name}' recorded.")
    print("2. **Responsibility**: Durable authority recorded in ApprovalStore.")

    print("\nCongratulations! You have completed the Expert curriculum.")
    print("============================================")


if __name__ == "__main__":
    main()
