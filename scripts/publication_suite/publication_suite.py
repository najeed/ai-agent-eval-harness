"""
publication_suite.py

Main entry point for the self-contained Publication Suite.
Provides a unified interface for conduction, aggregation, and reporting.
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="MultiAgentEval - Publication Suite (Zero-Touch)"
    )
    parser.add_argument(
        "--mode", choices=["pilot", "standard"], default="standard", help="Run mode"
    )
    parser.add_argument("--path", default="scenarios/", help="Scenario path")
    parser.add_argument(
        "--agent-name", default="Verified-Adapter-v1", help="Adapter name"
    )
    parser.add_argument("--protocol", default="http", help="Protocol")
    parser.add_argument(
        "--agent", default="http://localhost:5001/execute_task", help="Agent endpoint"
    )
    parser.add_argument(
        "--compare",
        help="Path to agents_inventory.yaml for multi-agent benchmark (Default: scripts/publication_suite/agents_inventory.yaml)",
    )
    parser.add_argument("--parallel", type=int, default=4, help="Worker count")

    args = parser.parse_args()

    print("=" * 60)
    print(" AGENTEVAL ADVANCED PUBLICATION SUITE (v4)")
    print("=" * 60)

    suite_dir = Path(__file__).parent.absolute()
    env = os.environ.copy()
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{suite_dir}{os.pathsep}{python_path}"

    # Identify agents to run
    agents_to_run = []
    if args.compare:
        import yaml

        inventory_path = Path(args.compare)
        if not inventory_path.exists():
            # Fallback to suite-relative path
            inventory_path = suite_dir / args.compare

        if not inventory_path.exists():
            print(f"Error: Inventory file {inventory_path} not found.")
            return
        with open(inventory_path, "r") as f:
            inventory = yaml.safe_load(f)
            agents_to_run = inventory.get("agents", [])
    else:
        agents_to_run = [
            {"name": args.agent_name, "protocol": args.protocol, "agent": args.agent}
        ]

    batch_dirs = []

    for agent in agents_to_run:
        print(f"\n" + "-" * 40)
        print(f" STARTING BENCHMARK: {agent['name']}")
        print("-" * 40)

        # 1. CONDUCT
        print("\nPhase 1: Conducting Evaluations...")
        cmd_conduct = [
            sys.executable,
            str(suite_dir / "conductor.py"),
            "--path",
            args.path,
            "--agent-name",
            agent["name"],
            "--protocol",
            agent["protocol"],
            "--agent",
            agent["agent"],
            "--parallel",
            str(args.parallel),
        ]
        if args.mode == "pilot":
            cmd_conduct.append("--pilot")

        subprocess.run(cmd_conduct, check=True, env=env)

        # Locate recent batch dir
        results_dir = Path("results")
        batches = sorted(
            [d for d in results_dir.iterdir() if d.is_dir()],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if not batches:
            print(f"Error: No results found for {agent['name']}.")
            continue

        batch_dir = batches[0]
        batch_dirs.append(batch_dir)

        # 2. AGGREGATE
        print("\nPhase 2: Aggregating Statistical Metrics...")
        subprocess.run(
            [
                sys.executable,
                str(suite_dir / "aggregator.py"),
                str(batch_dir / "manifest.json"),
            ],
            check=True,
            env=env,
        )

    if not batch_dirs:
        print("No successful batches to visualize.")
        return

    # 3. VISUALIZE (Comparative if multiple)
    print("\nPhase 3: Generating Comparative Leaderboards...")
    results_files = [str(d / "aggregated_results.json") for d in batch_dirs]
    cmd_html = [sys.executable, str(suite_dir / "html_builder.py")] + results_files
    if args.mode == "pilot":
        cmd_html.append("--pilot")
    subprocess.run(cmd_html, check=True, env=env)

    # 4. BUNDLE
    print("\nPhase 4: Creating Artifact Bundles...")
    for b_dir in batch_dirs:
        subprocess.run(
            [sys.executable, str(suite_dir / "bundle.py"), str(b_dir)],
            check=True,
            env=env,
        )

    print("\n" + "=" * 60)
    print(" PUBLICATION COMPLETE")
    print(f" Batches Processed: {len(batch_dirs)}")
    if len(batch_dirs) == 1:
        print(
            f" Leaderboard: {batch_dirs[0] / ('pilot_preview.html' if args.mode == 'pilot' else 'leaderboard.html')}"
        )
    else:
        print(
            f" Comparative Leaderboard: {batch_dirs[0].parent / ('pilot_preview.html' if args.mode == 'pilot' else 'leaderboard.html')} (Multi-Agent)"
        )
    print("=" * 60)


if __name__ == "__main__":
    main()
