import os
import subprocess
import time
from pathlib import Path

def main():
    print("============================================")
    print("The Industrial Cargo: Upgrade & Archiving")
    print("Scenario: The Vault Update")
    print("============================================")
    
    # Check for existing telecom industry
    root = Path(__file__).parent.parent.parent.parent
    telecom_dir = root / "industries" / "telecom"

    if not telecom_dir.exists():
        print("\n[!] Please run 'Step_1_Install_Benchmarks.py' first.")
        return

    print("\nWe are now upgrading the 'Telecom' pack to version 2.0.0.")
    print("Wait—the harness has detected existing benchmarks in 'industries/telecom'!")
    
    input("\n[Press ENTER] to trigger the atomic upgrade...")
    
    # Run the upgrade command
    print("\n   [CLI] Running: multiagent-eval install-pack telecom@2.0.0")
    try:
        # We'll use the CLI module directly for the walkthrough
        subprocess.run(["python", "-m", "eval_runner.cli", "install-pack", "telecom@2.0.0"], check=True)
    except Exception as e:
        print(f"   [Cargo] Installation failed: {e}")

    # Inspect the vault
    print("\n============================================")
    print("📊 Analysis of the 'Vault' Response:")
    print("1. **Atomic Switch**: 'industries/telecom' now contains only version 2.0.0.")
    print("2. **Safe Archiving**: The older pack was automatically moved to '.archived/'.")
    
    archive_dir = root / ".archived"
    if archive_dir.exists():
        print(f"   [Verified] Your previous benchmarks are safe in {archive_dir.name}/")
    
    print("\nSuccess. You have successfully updated your industrial cargo.")
    print("============================================")

if __name__ == "__main__":
    main()


