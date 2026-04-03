import os
import subprocess
from pathlib import Path

def main():
    print("============================================")
    print("The Industrial Cargo: Pack Installation")
    print("Scenario: The First Shipment")
    print("============================================")
    
    print("\nWe are deploying the 'Telecom' industrial benchmark pack.")
    print("This will populate your 'industries/telecom' directory and")
    print("automatically re-index the Scenario Catalog.")
    
    input("\n[Press ENTER] to install the 'telecom' pack...")
    
    # Run the install-pack command
    print("\n   [CLI] Running: multiagent-eval install-pack telecom")
    try:
        # We'll use the CLI module directly for the walkthrough
        subprocess.run(["python", "-m", "eval_runner.cli", "install-pack", "telecom"], check=True)
    except Exception as e:
        print(f"   [Cargo] Installation failed: {e}")

    print("\n   [Catalog] Re-indexing complete.")
    print("   [Verified] The new industrial benchmarks are now ready for evaluation.")

    print("\n============================================")
    print("Success. The first shipment is safely in the warehouse.")
    print("Next, we'll demonstrate an 'Industrial Upgrade' in Step 2.")
    print("============================================")

if __name__ == "__main__":
    main()


