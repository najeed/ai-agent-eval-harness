"""
conductor.py

Conductor for the Advanced Publication Suite.
Orchestrates eval-harness CLI runs and captures Flight Recorder logs.
"""

import argparse
import subprocess
import json
import os
import random
import hashlib
import time
import shutil
from pathlib import Path
from multiprocessing import Pool
from datetime import datetime


def run_worker(task):
    """Subprocess worker to run a single evaluation."""
    scenario_path, agent_name, protocol, agent_url, seed, output_dir, run_id = task

    # Use a dedicated sub-folder for this specific worker run to capture its log accurately
    worker_log_dir = output_dir / f"tmp_{run_id}"
    worker_log_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python",
        "-m",
        "eval_runner.cli",
        "evaluate",
        "--path",
        str(scenario_path),
        "--agent-name",
        agent_name,
        "--protocol",
        protocol,
        "--agent",
        agent_url,
    ]

    try:
        env = os.environ.copy()
        env["RUN_LOG_DIR"] = str(worker_log_dir)
        env["RUN_LOG_PER_RUN"] = "true"
        env["RUN_LOG_MASTER"] = "false"  # Only per-run logs for aggregation

        if seed is not None:
            env["PYTHONHASHSEED"] = str(seed)

        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        # Find the generated log file in worker_log_dir
        log_files = list(worker_log_dir.glob("*.jsonl"))
        if log_files:
            # Take the newest or only one
            source_log = sorted(log_files, key=lambda x: x.stat().st_mtime)[-1]
            target_log = output_dir / f"{run_id}.jsonl"
            shutil.move(str(source_log), str(target_log))
            shutil.rmtree(worker_log_dir)

            return {
                "run_id": run_id,
                "success": result.returncode == 0,
                "log_path": str(target_log),
                "scenario": scenario_path.name,
                "seed": seed,
            }
        else:
            return {
                "run_id": run_id,
                "success": False,
                "error": "No log file generated",
            }

    except Exception as e:
        return {"run_id": run_id, "success": False, "error": str(e)}


class Conductor:
    def __init__(self, args):
        self.args = args
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base_dir = Path("results") / f"batch_{self.timestamp}"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_scenario_subset(self):
        scenario_dir = Path(self.args.path)
        all_scenarios = list(scenario_dir.glob("*.json"))
        if self.args.pilot:
            return all_scenarios[:10]
        return all_scenarios

    def _generate_fingerprint(self):
        raw = f"{self.args.agent_name}-{self.timestamp}-{self.args.seed or 'none'}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def run(self):
        scenarios = self._get_scenario_subset()
        runs_per_scenario = self.args.runs if not self.args.pilot else 5

        tasks = []
        fingerprint = self._generate_fingerprint()

        print(f"🚀 [Conductor] Starting batch: {fingerprint}")

        idx = 0
        for scenario in scenarios:
            for i in range(runs_per_scenario):
                run_id = f"run_{idx:03d}"
                seed = (self.args.seed or 42) + idx
                tasks.append(
                    (
                        scenario,
                        self.args.agent_name,
                        self.args.protocol,
                        self.args.agent,
                        seed,
                        self.base_dir,
                        run_id,
                    )
                )
                idx += 1

        results = []
        # serial for pilot to avoid any logging race conditions, parallel otherwise
        if self.args.pilot:
            for t in tasks:
                results.append(run_worker(t))
                print(f"   [Pilot] Completed run {len(results)}/{len(tasks)}...")
        else:
            with Pool(processes=self.args.parallel) as pool:
                for i, res in enumerate(pool.imap_unordered(run_worker, tasks)):
                    results.append(res)
                    if i % 5 == 0:
                        print(f"   [Progress] {i}/{len(tasks)} runs complete...")

        metadata = {
            "fingerprint": fingerprint,
            "timestamp": self.timestamp,
            "agent_name": self.args.agent_name,
            "base_dir": str(self.base_dir),
            "runs": results,
        }
        meta_path = self.base_dir / "manifest.json"
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"✅ [Conductor] Batch complete. Manifest saved: {meta_path}")
        return meta_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="scenarios/", help="Scenario directory")
    parser.add_argument(
        "--agent-name", default="Generic-Adapter", help="Target agent name"
    )
    parser.add_argument("--protocol", default="http", help="Protocol")
    parser.add_argument(
        "--agent", default="http://localhost:5001/execute_task", help="Agent endpoint"
    )
    parser.add_argument("--runs", type=int, default=10, help="Runs per scenario")
    parser.add_argument("--parallel", type=int, default=4, help="Worker count")
    parser.add_argument("--pilot", action="store_true", help="Pilot mode")
    parser.add_argument("--seed", type=int, help="Base seed")

    args = parser.parse_args()
    conductor = Conductor(args)
    conductor.run()
