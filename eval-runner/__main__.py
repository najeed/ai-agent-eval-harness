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


def main():
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
    parser.add_argument(
        "--export",
        type=str,
        choices=["csv", "json", "html"],
        help="Export format for evaluation results (csv, json, or html).",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path for exported results. If not specified, auto-generated filename will be used.",
    )
    parser.add_argument(
        "--include-charts",
        action="store_true",
        help="Include charts in HTML export (only applicable for HTML format).",
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

    # --- 2. Loop through and execute each scenario ---
    for i, scenario_path in enumerate(scenarios_to_run):
        print("\n" + "#" * 80)
        print(
            f"RUNNING SCENARIO {i+1}/{len(scenarios_to_run)}: {scenario_path.relative_to(base_path)}"
        )
        print("#" * 80)

        # 1. Load the evaluation scenario
        try:
            scenario_data = loader.load_scenario(scenario_path)
            print(f"✅ Successfully loaded scenario: {scenario_data.get('title')}")
        except Exception as e:
            print(f"❌ Error loading scenario: {e}")
            continue  # Skip to the next scenario

        # 2. Run the evaluation engine
        print("⚙️  Running evaluation engine...")
        results = engine.run_evaluation(scenario_data)
        print("✅ Engine run complete.")

        # 3. Generate and display the report
        print("📊 Generating report...")
        reporter.generate_report(scenario_data, results)
        
        # 4. Export results if requested
        if args.export:
            print(f"📤 Exporting results in {args.export.upper()} format...")
            
            # Generate output filename if not provided
            if args.output:
                output_path = args.output
            else:
                scenario_id = scenario_data.get('scenario_id', 'scenario')
                timestamp = results.timestamp.replace(':', '-').replace('.', '-')
                output_path = f"{scenario_id}_{timestamp}.{args.export}"
            
            try:
                if args.export == "csv":
                    results.export_csv(output_path)
                elif args.export == "json":
                    results.export_json(output_path)
                elif args.export == "html":
                    results.export_html(output_path, include_charts=args.include_charts)
                    
                print(f"✅ Results exported successfully to: {output_path}")
            except Exception as e:
                print(f"❌ Error exporting results: {e}")

    print("\n" + "=" * 80)
    print("✅ ALL EVALUATIONS FINISHED.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
