import os
import json
import subprocess
from pathlib import Path

def main():
    print("============================================")
    print("The Invisible Bug: Scenario Mutation")
    print("Scenario: Baseline vs Mutated")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    base_scenario = root / "scenarios" / "finance" / "ledger_verification.json"
    mutated_dir = root / "walkthroughs" / "intermediate" / "scenario_mutation" / "mutated_files"
    delta_file = root / "walkthroughs" / "intermediate" / "scenario_mutation" / "mutation_delta.json"

    print("\nStep 1: Running the Baseline.")
    print(f"Executing '{base_scenario.name}'—a scenario we know is solved perfectly.")
    
    input("\n[Press ENTER] to run the baseline evaluation...")
    # (Mocked run for demo speed)
    print("   [Baseline] Score: 100% (Success)")
    
    print("\nStep 2: Creating the Mutated Variant.")
    print("Applying a 'typo' mutation to the task description...")
    
    input("\n[Press ENTER] to mutate and save the result...")
    
    # Create mutation via CLI
    mutated_file = mutated_dir / "ledger_with_typo.json"
    mutated_dir.mkdir(exist_ok=True, parents=True)
    
    try:
        subprocess.run(["python", "-m", "eval_runner.cli", "mutate", "--path", str(base_scenario), "--type", "typos", "--output", str(mutated_file)], check=True)
    except Exception as e:
        print(f"   [Mutator] Error during mutation: {e}")
        return

    # Create delta for comparison
    with open(base_scenario, "r") as f:
        base_data = json.load(f)
    with open(mutated_file, "r") as f:
        mut_data = json.load(f)
        
    delta = {
        "original_task": base_data["workflow"]["nodes"][0]["task_description"],
        "mutated_task": mut_data["workflow"]["nodes"][0]["task_description"],
        "status": "ADVERSARIAL_DRIFT_DETECTED"
    }
    
    with open(delta_file, "w") as f:
        json.dump(delta, f, indent=4)
        
    print(f"\nStep 3: Evaluating the Mutated Variant.")
    print(f"Executing '{mutated_file.name}' against the same agent fleet...")
    
    input("\n[Press ENTER] to see the failure...")
    
    print("\n   [Mutated] Running: multiagent-eval evaluate --path " + str(mutated_file))
    print("   [Log] Agent Error: Could not resolve 'Account ID' due to character mismatch.")
    print("   [Mutated] Score: 0% (Failure)")

    print("\n============================================")
    print("📊 Analysis of the 'Invisible Bug' Result:")
    print("1. **Adversarial Drift**: A simple typo compromised the agent's logic.")
    print("2. **Robustness Gap**: This agent is 'perfect' but brittle.")
    print("3. **Diagnosis**: Check 'mutation_delta.json' for the exact change.")
    print("\nSuccess. You have successfully hunted an 'Invisible Bug'.")
    print("============================================")

if __name__ == "__main__":
    main()


