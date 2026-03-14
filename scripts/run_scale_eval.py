"""
run_scale_eval.py

Robust orchestrator for large-scale evaluation campaigns.
Supports parallel execution, seeded randomness, retry logic, and publication data export.
"""

import argparse
import asyncio
import subprocess
import json
import os
import random
from pathlib import Path
from multiprocessing import Pool

def run_single_eval(args_tuple):
    """Worker function for parallel evaluation."""
    scenario_path, agent_name, protocol, agent_url, seed, retry_count = args_tuple
    
    cmd = [
        "python", "-m", "eval_runner.cli", "evaluate",
        "--path", str(scenario_path),
        "--agent-name", agent_name,
        "--protocol", protocol,
        "--agent", agent_url,
        "--per-run-logs"
    ]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
        
    print(f"[ScaleRunner] Executing: {' '.join(cmd)}")
    
    for attempt in range(retry_count + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        print(f"   [Retry] Attempt {attempt+1} failed for {scenario_path.name}. Retrying...")
        
    return False

async def main():
    parser = argparse.ArgumentParser(description="AI Agent Eval Scale Runner")
    parser.add_argument("--path", required=True, help="Path to scenario directory")
    parser.add_argument("--agent-name", default="Scale-Agent-X", help="Name for leaderboard")
    parser.add_argument("--protocol", default="http", help="Agent protocol")
    parser.add_argument("--agent", default="http://localhost:5001/execute_task", help="Agent URL")
    parser.add_argument("--runs", type=int, default=10, help="Number of total runs to perform")
    parser.add_argument("--parallel", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--pilot", action="store_true", help="Quick-run mode (3 runs, 1 worker)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--seed", type=int, help="Base seed for reproducibility")
    parser.add_argument("--retries", type=int, default=1, help="Number of retries per failed evaluation")
    
    args = parser.parse_args()
    
    if args.pilot:
        args.runs = 3
        args.parallel = 1
        print("[ScaleRunner] Pilot mode active: 3 runs, serial execution.")

    scenario_dir = Path(args.path)
    scenarios = list(scenario_dir.glob("*.json"))
    
    if not scenarios:
        print(f"[Error] No scenarios found in {args.path}")
        return

    # Prepare seeds
    base_seed = args.seed if args.seed is not None else random.randint(0, 100000)
    seeds = [base_seed + i for i in range(args.runs)]

    # Expand list to match requested runs
    all_tasks = []
    runs_per_scenario = (args.runs // len(scenarios)) + 1
    task_idx = 0
    for s in scenarios:
        for _ in range(runs_per_scenario):
            if task_idx < args.runs:
                all_tasks.append((s, args.agent_name, args.protocol, args.agent, seeds[task_idx], args.retries))
                task_idx += 1

    print(f"[ScaleRunner] Starting scale run: {len(all_tasks)} total evaluations across {args.parallel} workers (Base Seed: {base_seed})...")
    
    checkpoint_path = Path("reports/scale_checkpoint.json")
    completed = 0
    if args.resume and checkpoint_path.exists():
        with open(checkpoint_path, "r") as f:
            completed = json.load(f).get("completed", 0)
            print(f"[ScaleRunner] Resuming from task {completed}...")
            all_tasks = all_tasks[completed:]

    with Pool(processes=args.parallel) as pool:
        for i, success in enumerate(pool.imap_unordered(run_single_eval, all_tasks)):
            if success:
                completed += 1
                if i % 5 == 0:
                    try:
                        with open(checkpoint_path, "w") as f:
                            json.dump({"completed": completed}, f)
                    except: pass
                    print(f"[ScaleRunner] Progress: {completed}/{args.runs} runs completed.")

    print("\n" + "="*40)
    print(f"[ScaleRunner] Scale campaign finished!")
    print(f"[ScaleRunner] Total Successful Runs: {completed}")
    print(f"[ScaleRunner] Results aggregated in reports/publication_data.json")
    print("="*40)

if __name__ == "__main__":
    asyncio.run(main())
