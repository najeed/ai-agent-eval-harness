import os
import json
import subprocess
from pathlib import Path

def main():
    print("============================================")
    print("Bridge-Building at Aethelgard Industrial")
    print("Scenario: The Multilingual Agent")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    config_path = root / "eval_config.json"
    shim_path = root / "walkthroughs" / "beginner" / "adapters" / "local_agent_shim.py"

    print(f"\nYour current agent configuration is located in: {config_path.name}")
    print("Most agents run on remote servers (HTTP), but sometimes we need to evaluate")
    print("a script that exists right here in the repository.")
    
    input("\n[Press ENTER] to switch to 'Local' evaluation...")
    
    # 1. Update config
    new_config = {
        "industry": "general",
        "agent_api_url": f"local://{shim_path.absolute()}",
        "max_turns": 10
    }
    
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(new_config, f, indent=4)
        
    print("\n   [Config] Successfully updated 'eval_config.json' to use the Local Agent Shim.")
    print(f"   [Config] Endpoint: {new_config['agent_api_url']}")
    
    print("\n============================================")
    print("The Bridge is built. Now, run this command:")
    print("multiagent-eval evaluate --path scenarios/telecom/connectivity_check.json")
    print("============================================")

if __name__ == "__main__":
    main()


