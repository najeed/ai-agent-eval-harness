"""
conductor.py

Conductor for the Advanced Publication Suite.
Orchestrates eval-harness CLI runs and captures Flight Recorder logs.
"""

import argparse
import json
import os
import subprocess
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

from eval_runner.utils import crypto


def run_worker(task):
    """Subprocess worker to run a single evaluation."""
    scenario_path, agent_name, protocol, agent_url, seed, output_dir, run_id = task

    # Compose an isolated local reference provider for this worker.  The
    # conductor subsequently queries that provider; it never discovers traces.
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
        env["RUN_LOG_MASTER"] = "false"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        if seed is not None:
            env["PYTHONHASHSEED"] = str(seed)

        result = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")

        from eval_runner.runtime_services import compose_local_run_store

        run_store = compose_local_run_store(worker_log_dir)
        records = run_store.list_runs(limit=2)
        if len(records) == 1:
            provider_run_id = records[0]["run_id"]
            return {
                "run_id": provider_run_id,
                "success": result.returncode == 0,
                "provider_log_dir": str(worker_log_dir),
                "scenario": scenario_path.name,
                "seed": seed,
            }
        return {
            "run_id": run_id,
            "success": False,
            "error": "No log file generated: provider did not publish exactly one run",
        }

    except Exception as e:
        return {"run_id": run_id, "success": False, "error": str(e)}


class Conductor:
    def __init__(self, args):
        self.args = args
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = getattr(self.args, "output_dir", None)
        b_id = getattr(self.args, "batch_id", None)
        if out_dir and isinstance(out_dir, (str, Path)):
            self.base_dir = Path(out_dir)
        elif b_id and isinstance(b_id, str):
            self.base_dir = Path("results") / b_id
        else:
            self.base_dir = Path("results") / f"batch_{self.timestamp}"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_scenario_subset(self):
        scenario_dir = Path(self.args.path)
        all_scenarios = list(scenario_dir.glob("*.json"))
        return all_scenarios

    def _generate_fingerprint(self):
        raw = f"{self.args.agent_name}-{self.timestamp}-{self.args.seed or 'none'}"
        return crypto.content_hash(raw, length=6)

    def run(self):
        scenarios = self._get_scenario_subset()
        runs_per_scenario = self.args.runs if not self.args.pilot else 5

        tasks = []
        fingerprint = self._generate_fingerprint()

        print(f"🚀 [Conductor] Starting batch: {fingerprint}")

        idx = 0
        for scenario in scenarios:
            for i in range(runs_per_scenario):  # noqa: B007
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
            for i, t in enumerate(tasks):
                print(f"   [Pilot] Running run {i + 1}/{len(tasks)}...")
                res = run_worker(t)
                results.append(res)
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
    parser.add_argument("--agent-name", default="Generic-Adapter", help="Target agent name")
    parser.add_argument("--protocol", default="http", help="Protocol")
    parser.add_argument(
        "--agent", default="http://localhost:5001/execute_task", help="Agent endpoint"
    )
    parser.add_argument("--runs", type=int, default=10, help="Runs per scenario")
    parser.add_argument("--parallel", type=int, default=4, help="Worker count")
    parser.add_argument("--pilot", action="store_true", help="Pilot mode")
    parser.add_argument("--seed", type=int, help="Base seed")
    parser.add_argument("--batch-id", help="Explicit batch identifier (deterministic)")
    parser.add_argument("--output-dir", help="Explicit output directory")

    args = parser.parse_args()
    conductor = Conductor(args)
    conductor.run()

    conductor.run()
