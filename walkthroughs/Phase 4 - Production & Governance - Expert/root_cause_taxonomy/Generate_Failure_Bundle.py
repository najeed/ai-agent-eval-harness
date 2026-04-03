import json
import os
from pathlib import Path

def main():
    print("============================================")
    print("MultiAgentEval: Failure Bundle Generator")
    print("============================================")
    print("\n   [Capture] Populating 10 varied failure traces for investigation...")
    
    failures = [
        {"id": "fail_001", "industry": "telecom", "issue": "Agent failed to resolve the signal path."},
        {"id": "fail_002", "industry": "finance", "issue": "Agent credited the wrong account."},
        {"id": "fail_003", "industry": "telecom", "issue": "Agent entered an infinite retry loop."},
        {"id": "fail_004", "industry": "general", "issue": "Agent used a deprecated tool."},
        {"id": "fail_005", "industry": "finance", "issue": "Agent ignored the audit threshold."},
        {"id": "fail_006", "industry": "telecom", "issue": "Agent failed to authenticate."},
        {"id": "fail_007", "industry": "general", "issue": "Agent hallucinated a response."},
        {"id": "fail_008", "industry": "finance", "issue": "Agent used an invalid JSON schema."},
        {"id": "fail_009", "industry": "telecom", "issue": "Agent timed out during calculation."},
        {"id": "fail_010", "industry": "general", "issue": "Agent refused a valid request."}
    ]
    
    bundle_path = Path(__file__).parent / "failed_trace_bundle.json"
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(failures, f, indent=4)
        
    print(f"\n   [Success] Failure bundle created: {bundle_path.name}")
    print("============================================")

if __name__ == "__main__":
    main()

