import json
from pathlib import Path

def main():
    print("============================================")
    print("MultiAgentEval: Parity Drift Simulator")
    print("============================================")
    print("\n   [Drifter] Introducing a subtle configuration discrepancy...")
    
    # Golden State (Reference)
    golden_state = {
        "env_version": "1.2.3",
        "python_runtime": "3.9.12",
        "api_endpoint": "https://api.aethelgard.io/v1",
        "max_concurrency": 50,
        "secure_mode": True
    }
    
    # Drifting State (Modified)
    drifting_state = golden_state.copy()
    drifting_state["max_concurrency"] = 60  # The hidden drift factor
    drifting_state["env_version"] = "1.2.3-BETA" # Version mismatch
    
    output_path = Path(__file__).parent / "registry_drift_sample.json"
    repo_data = {
        "golden": golden_state,
        "staging": drifting_state,
        "status": "DRIFT_PENDING"
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(repo_data, f, indent=4)
        
    print(f"\n   [Success] Drift snapshot created: {output_path.name}")
    print("============================================")

if __name__ == "__main__":
    main()

