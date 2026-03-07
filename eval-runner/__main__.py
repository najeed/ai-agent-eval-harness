"""
__main__.py

This is the entry point for the AI Agent Evaluation Harness. It parses command-line arguments, loads scenarios, runs the evaluation engine, and generates reports.

Typical usage:
    python -m eval-runner --industry accounting --scenario accounts_payable/001.json
"""
# eval-runner/__main__.py

import argparse
from . import loader
from . import engine
from . import reporter
from pathlib import Path
import sys


import asyncio

async def main_async():
    """
    Main entry point for the AI Agent Evaluation Harness.

    Parses command-line arguments to determine which evaluations to run, loads the necessary scenarios, executes the evaluation engine, and generates a report of the results.

    Args:
        None

    Returns:
        None

    Example:
        $ python -m eval-runner --industry accounting --scenario accounts_payable/001.json
    """
    parser = argparse.ArgumentParser(description="AI Agent Evaluation Harness")
    parser.add_argument(
        "--industry",
        type=str,
        required=True,
        help="The industry to evaluate (e.g., 'telecom').",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        nargs="+",  # Accept one or more file or directory paths
        required=True,
        help="One or more scenario files or directories to run (e.g., 'customer_service/01_billing_dispute.json' or 'customer_service').",
    )

    args = parser.parse_args()

    print(f"🚀 Starting evaluation for industry '{args.industry}'...")

    # --- 1. Discover all scenario files ---
    base_path = Path(__file__).parent.parent / "industries"
    scenarios_to_run = []

    for scenario_path_part in args.scenario:
        # Construct the full path to the scenario file or directory
        full_path = base_path / args.industry / "scenarios" / scenario_path_part
        if scenario_path_part=="all":
            scenario_path_part = "" # Handle 'all' as a special case to include all scenarios in that industry
        if not full_path.exists():
            print(f"⚠️ Warning: Path not found, skipping: {full_path}")
            continue

        if full_path.is_dir():
            # If it's a directory, find all .json files recursively
            print(f"🔎 Found directory: {full_path}. Searching for scenarios...")
            json_files = sorted(full_path.rglob("*.json"))
            if not json_files:
                print(f"   -> No .json scenarios found in {full_path}")
            scenarios_to_run.extend(json_files)
        elif full_path.is_file() and full_path.suffix == ".json":
            # If it's a JSON file, add it directly
            scenarios_to_run.append(full_path)
        else:
            print(
                f"⚠️ Warning: Path is not a valid .json file or directory, skipping: {full_path}"
            )

    # Remove duplicates that might occur if a file and its parent dir are both specified
    scenarios_to_run = sorted(list(set(scenarios_to_run)))

    if not scenarios_to_run:
        print(f"❌ Error: No valid scenario files found to run.")
        sys.exit(1)

    print(f"\n✅ Discovered {len(scenarios_to_run)} total scenario(s) to run.")

    # --- 2. Load all scenarios ---
    loaded_scenarios = []
    
    for i, scenario_path in enumerate(scenarios_to_run):
        try:
            scenario_data = loader.load_scenario(scenario_path)
            loaded_scenarios.append({"path": scenario_path, "data": scenario_data})
        except Exception as e:
            print(f"❌ Error loading scenario {scenario_path}: {e}")
            continue

    print(f"✅ Successfully loaded {len(loaded_scenarios)} scenarios.")

    # --- 3. Execute all scenarios concurrently ---
    print("\n" + "#" * 80)
    print("⚙️  Running evaluation engine concurrently for all scenarios...")
    print("#" * 80)

    # Creating tasks for concurrent execution
    tasks = []
    for item in loaded_scenarios:
        tasks.append(engine.run_evaluation(item["data"]))
    
    # Run them all
    results_list = await asyncio.gather(*tasks)
    print("✅ Engine runs complete.")

    # --- 4. Generate and display reports sequentially ---
    for item, results in zip(loaded_scenarios, results_list):
        print("\n" + "#" * 80)
        print(f"REPORT FOR: {item['path'].relative_to(base_path)}")
        print("#" * 80)
        reporter.generate_report(item["data"], results)

    print("\n" + "=" * 80)
    print("✅ ALL EVALUATIONS FINISHED.")
    print("=" * 80 + "\n")


def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
