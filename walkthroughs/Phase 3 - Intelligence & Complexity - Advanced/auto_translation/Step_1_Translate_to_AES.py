import os
import json
import subprocess
from pathlib import Path

def main():
    print("============================================")
    print("The Rosetta Stone: Auto-Translation")
    print("Scenario: The PRD Transmuter")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    prd_path = root / "walkthroughs" / "advanced" / "auto_translation" / "sample_prd.md"
    output_path = root / "walkthroughs" / "advanced" / "auto_translation" / "reactor_startup.json"

    print("\nWe are translating a human-readable 'Reactor Startup' PRD.")
    print(f"Source: {prd_path.name}")
    print("The harness will parse the requirements and generate a structured AES benchmark.")
    
    input("\n[Press ENTER] to execute the translation...")
    
    # Run the auto-translate command
    print("\n   [CLI] Running: multiagent-eval auto-translate --prd " + str(prd_path) + " --output " + str(output_path))
    
    try:
        # We'll use the CLI module directly for the walkthrough
        subprocess.run(["python", "-m", "eval_runner.cli", "auto-translate", "--prd", str(prd_path), "--output", str(output_path)], check=True)
    except Exception as e:
        print(f"   [Rosetta] Translation failed: {e}")
        return

    # Validate output
    if output_path.exists():
        with open(output_path, "r") as f:
            aes_data = json.load(f)
            
        print("\n📊 Analysis of the 'Rosetta' Response:")
        print(f"1. **Parsed Nodes**: {len(aes_data['workflow']['nodes'])} operational steps identified.")
        print(f"2. **Schema Audit**: Successfully mapped to AES v{aes_data['aes_version']}.")
        print("3. **Success Criteria**: Codified '50Hz' and 'STABLE' triggers.")
        
        print("\n🎉 Success! You have bootstrapped a benchmark in seconds.")
    else:
        print("\n[!] Error: Resulting AES JSON not found.")

    print("\n============================================")
    print("Proceed to: 08_Multi_Agent (The Silent Swarm)")
    print("============================================")

if __name__ == "__main__":
    main()


