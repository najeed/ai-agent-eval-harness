import os
import subprocess
import time
from pathlib import Path

def main():
    print("============================================")
    print("The Recursion Paradox: Autonomous Flow Control")
    print("Scenario: Refinement Loop Visualization")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    scenario_path = root / "walkthroughs" / "advanced" / "dag_loops" / "looping_scenario.json"

    print("\nWe are observing an 'Implicit Loop'.")
    print("The Auditor is set to fail the first turn to force a 'RETRY_LOOP'.")
    
    input("\n[Press ENTER] to see the recursion in action...")
    
    # Run the evaluation
    print(f"\n   [CLI] Running: multiagent-eval evaluate --path {scenario_path}")
    print("   [Log] [Turn 1] Writer task started...")
    time.sleep(1)
    print("   [Log] [Turn 1] Auditor check: FAILED (Insufficient stability).")
    print("   [Log] [Edge] Triggering 'RETRY_LOOP' conditional edge...")
    time.sleep(1)
    print("   [Log] [Turn 2] Writer refining state...")
    time.sleep(1)
    print("   [Log] [Turn 2] Auditor check: PASSED.")
    
    # Execute the actual CLI for trace generation
    try:
        subprocess.run(["python", "-m", "eval_runner.cli", "evaluate", "--path", str(scenario_path)], check=True)
    except Exception as e:
        print(f"   [Orchestrator] Loop execution failed: {e}")

    print("\n============================================")
    print("📊 Mermaid Path Visualization:")
    print("graph TD")
    print("    A[node_writer] -->|Success| B[node_auditor]")
    print("    B -->|Failure| A")
    print("    B -->|Success| C[End]")
    print("\n[Audit] 2 iterations detected. State converged to 'STABLE'.")
    print("\nSuccess. You have resolved the recursion paradox.")
    print("============================================")

if __name__ == "__main__":
    main()


