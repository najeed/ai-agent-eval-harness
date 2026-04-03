import os
import json
import random
from pathlib import Path

def main():
    print("============================================")
    print("MultiAgentEval: Root Cause Taxonomy")
    print("Scenario: The Forensic Heatmap")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    bundle_path = root / "walkthroughs" / "Phase 4 - Production & Governance - Expert" / "root_cause_taxonomy" / "failed_trace_bundle.json"
    output_path = root / "walkthroughs" / "Phase 4 - Production & Governance - Expert" / "root_cause_taxonomy" / "failure_heatmap.json"

    if not bundle_path.exists():
        print("\n[!] Error: 'failed_trace_bundle.json' not found. Please run 'Generate_Failure_Bundle.py' first.")
        return

    with open(bundle_path, "r") as f:
        failures = json.load(f)

    print(f"\nWe have detected {len(failures)} failures in our industrial fleet.")
    print("We will now categorize them into the 'AES Root Cause Taxonomy'.")
    input("\n[Press ENTER] to starting the triage...")
    
    taxonomy_categories = ["Reasoning", "Tool_Use", "Domain_Knowledge", "Safety_Violation"]
    results = {}

    for failure in failures:
        # Simulated LLM/Manual categorization
        category = random.choice(taxonomy_categories)
        results[failure["id"]] = {
            "industry": failure["industry"],
            "root_cause": category,
            "severity": random.choice(["Medium", "High", "Critical"])
        }
        print(f"   [Analyzed] {failure['id']}: {failure['issue']} -> {category}")

    # Generate the heatmap
    heatmap = {
        "metadata": {"name": "Industrial Fleet Heatmap", "id": "heatmap_001"},
        "statistics": {
            "total_failures": len(failures),
            "distribution": {cat: sum(1 for itm in results.values() if itm["root_cause"] == cat) for cat in taxonomy_categories}
        },
        "critical_sectors": ["telecom"] if any(itm["industry"] == "telecom" and itm["severity"] == "Critical" for itm in results.values()) else []
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(heatmap, f, indent=4)

    print("\n============================================")
    print("📊 Forensic Heatmap Analysis:")
    for cat, count in heatmap["statistics"]["distribution"].items():
        print(f" - {cat}: {count} occurrences")
    
    print(f"\n[Success] Heatmap generated in: {output_path.name}")
    print("\nTake this to the engineering team. It shows where your fleet is failing.")
    print("============================================")

if __name__ == "__main__":
    main()

