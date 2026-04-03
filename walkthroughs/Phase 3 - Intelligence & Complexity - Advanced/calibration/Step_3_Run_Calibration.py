import os
import subprocess
import sys

def main():
    print("\n" + "="*60)
    print("WALKTHROUGH: STEP 3 - RUN CALIBRATION")
    print("="*60)
    print("\nIn this step, we will use the MultiAgentEval CLI to measure")
    print("how closely the 'GPT-4o' judge matched our 'Human' ground truth.")
    print("\n[Executing CLI Command]:")
    print("multiagent-eval calibrate --path Step_1_Evaluation_Trace.jsonl --golden Step_2_Human_Ground_Truth.json")
    print("-" * 60)
    
    # Construct paths relative to this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    trace_path = os.path.join(base_dir, "Step_1_Evaluation_Trace.jsonl")
    golden_path = os.path.join(base_dir, "Step_2_Human_Ground_Truth.json")
    
    # Run the calibration command via the python module
    cmd = [
        sys.executable, "-m", "eval_runner.cli", 
        "calibrate", 
        "--path", trace_path, 
        "--golden", golden_path
    ]
    
    try:
        # Part 1: Good Judge
        print("PART 1: THE ACCURATE JUDGE")
        subprocess.run(cmd, check=True)
        
        # Part 2: Bad (Mutated) Judge
        print("\n" + "="*60)
        print("PART 2: THE BIASED (BAD) JUDGE")
        print("="*60)
        print("Now we run calibration on a judge that 'inflates' success scores.")
        
        mutated_path = os.path.join(base_dir, "Step_4_Mutated_Bad_Judge.jsonl")
        cmd_bad = cmd.copy()
        cmd_bad[5] = mutated_path # Replace the value for --path (index 5)
        
        subprocess.run(cmd_bad, check=True)

        print("\n" + "="*60)
        print("WALKTHROUGH ANALYSIS")
        print("="*60)
        print("1. Compare the MAE: Part 2 should have a significantly HIGHER MAE.")
        print("2. Compare the F1 Score: Part 2 should suggest an extreme threshold (e.g. 0.95)")
        print("   because the judge is 'too optimistic' to be trusted at 0.5.")
        print("="*60 + "\n")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Walkthrough failed: {e.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    main()


