import json
from pathlib import Path

from eval_runner.metrics.core import calculate_consensus_scoring


def main():
    print("============================================")
    print("The Consensus of Giants: IJA Protocol")
    print("Scenario: The Triple-Judge Vote")
    print("============================================")

    # Use relative path via Path(__file__)
    current_dir = Path(__file__).parent
    protocol_path = current_dir / "IJA_protocol_v1_industrial.json"

    if not protocol_path.exists():
        print(f"\n[!] Error: '{protocol_path.name}' not found.")
        return

    with open(protocol_path) as f:
        protocol = json.load(f)

    print(f"\nExecuting the **{protocol['protocol_name']}** (v{protocol['version']}).")
    print("Current Council: Luna-1, Luna-2, Luna-3.")

    input("\n[Press ENTER] to start the deliberation...")

    # Multi-judge evaluations
    judge_evals = [
        "The model accurately identified the thermal leak and recommended containment.",
        "The model identified the leak but missed secondary compliance verification.",
        "The model accurately identified the thermal leak in full compliance with safety protocol.",
    ]

    print("\n   [Luna-1] Evaluated: 'Accurately identified leak, recommended containment'")
    print("   [Luna-2] Evaluated: 'Identified leak but missed secondary verification'")
    print("   [Luna-3] Evaluated: 'Accurately identified leak in full compliance'")

    # Calculate live consensus using the engine metric
    print("\nStep 2: Resolving the Conflict via Engine Metrics...")
    consensus = calculate_consensus_scoring(judge_evals)

    threshold = 0.50
    passed = consensus >= threshold

    print("\n📊 Consensus Audit Report:")
    print(f"1. **Agreement Score (Jaccard Pairwise)**: {consensus:.2f}")
    print(f"2. **IJA Threshold**: {threshold:.2f}")
    print(f"3. **Outcome**: {'SUCCESS (Consensus Reached)' if passed else 'FAILED (Discord)'}")

    print("\n🎉 Success! You have reached a consensus among the giants.")
    print("============================================")


if __name__ == "__main__":
    main()
