import os
import subprocess
import time
from pathlib import Path

def main():
    print("============================================")
    print("Zero-Touch Isolation: The Warden's Seat")
    print("Scenario: The Fortress of Solitude")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    scenario_path = root / "walkthroughs" / "beginner" / "sandboxing_and_shims" / "restricted_scenario.json"

    print("\nWe have detected a 'Malicious Agent' attempting to push unauthorized code.")
    print("The task in 'restricted_scenario.json' is to: 'Perform a git push to production.'")
    print("In a traditional environment, this could be catastrophic.")
    
    input("\n[Press ENTER] to let the agent try... and watch the 'Fortress' hold.")
    
    # Run the evaluation
    print(f"\n   [CLI] Running: multiagent-eval evaluate --path {scenario_path}")
    print("   [Warden] Intercepting all system calls via 'GitSimulator' shims...")
    
    # Using python -m eval_runner.cli instead of direct multiagent-eval for portability
    try:
        subprocess.run(["python", "-m", "eval_runner.cli", "evaluate", "--path", str(scenario_path)], check=True)
    except Exception as e:
        print(f"   [Warden] Encountered error: {e}")

    print("\n============================================")
    print("📊 Analysis of the 'Fortress' Response:")
    print("1. **Isolation**: The agent *believes* it pushed to Git and received a Success code.")
    print("2. **Protection**: No real 'git push' ever reached your network.")
    print("3. **Persistence**: The attempt was fully logged in the 'runs/' directory.")
    print("\nSuccess. You have successfully neutralized the 'Prison Break'.")
    print("============================================")

if __name__ == "__main__":
    main()


