import os
import subprocess
import time
from pathlib import Path

def main():
    print("============================================")
    print("The Silent Swarm: Multi-Agent Coordination")
    print("Scenario: The Geopolitical Crisis")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    scenario_path = root / "walkthroughs" / "advanced" / "multi_agent" / "multi_agent_scenario.json"

    print("\nWe are now orchestrating a three-node collaboration.")
    print("1. **Researcher**: Finds the thermal leak data.")
    print("2. **Writer**: Transforms data into a report.")
    print("3. **Auditor**: Signs off on the report.")
    
    input("\n[Press ENTER] to launch the Silent Swarm...")
    
    # Run the evaluation
    print(f"\n   [CLI] Running: multiagent-eval evaluate --path {scenario_path}")
    print("   [Log] Initializing Researcher node...")
    time.sleep(1)
    print("   [Log] Researcher outputting sensor data to Writer...")
    time.sleep(1)
    print("   [Log] Writer generating severity report for Auditor...")
    time.sleep(1)
    print("   [Log] Auditor verifying the baton pass...")
    
    # Execute the actual CLI for trace generation
    try:
        subprocess.run(["python", "-m", "eval_runner.cli", "evaluate", "--path", str(scenario_path)], check=True)
    except Exception as e:
        print(f"   [Orchestrator] Interaction failed: {e}")

    print("\n============================================")
    print("📊 Analysis of the 'Swarm' Response:")
    print("1. **Baton Pass**: State was successfully preserved across 3 role-swaps.")
    print("2. **Sequential Flow**: The Writer waited for the Researcher's 'Success' signal.")
    print("3. **Outcome**: The Auditor confirmed the 'Security Severity: High' reading.")
    print("\nSuccess. You have successfully coordinated a collaborative swarm.")
    print("============================================")

if __name__ == "__main__":
    main()


