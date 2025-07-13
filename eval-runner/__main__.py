# eval-runner/__main__.py

import argparse
import loader
import engine
import reporter
from pathlib import Path

def main():
    """
    Main entry point for the AI Agent Evaluation Harness.
    
    Parses command-line arguments to determine which evaluations to run,
    loads the necessary scenarios, executes the evaluation engine,
    and generates a report of the results.
    """
    parser = argparse.ArgumentParser(description="AI Agent Evaluation Harness")
    parser.add_argument(
        "--industry", 
        type=str, 
        required=True, 
        help="The industry to evaluate (e.g., 'telecom')."
    )
    parser.add_argument(
        "--scenario", 
        type=str, 
        required=True, 
        help="The scenario file to run (e.g., 'customer_service/01_billing_dispute.json')."
    )
    
    args = parser.parse_args()
    
    print(f"🚀 Starting evaluation for industry '{args.industry}' with scenario '{args.scenario}'...")
    
    # Construct the path to the scenario file
    base_path = Path(__file__).parent.parent / "industries"
    scenario_path = base_path / args.industry / "scenarios" / args.scenario
    
    if not scenario_path.exists():
        print(f"❌ Error: Scenario file not found at {scenario_path}")
        return

    # 1. Load the evaluation scenario
    try:
        scenario_data = loader.load_scenario(scenario_path)
        print(f"✅ Successfully loaded scenario: {scenario_data.get('title')}")
    except Exception as e:
        print(f"❌ Error loading scenario: {e}")
        return

    # 2. Run the evaluation engine
    # The engine will simulate the agent's interaction based on the scenario tasks
    print("⚙️  Running evaluation engine...")
    results = engine.run_evaluation(scenario_data)
    print("✅ Engine run complete.")

    # 3. Generate and display the report
    print("📊 Generating report...")
    reporter.generate_report(scenario_data, results)
    print("✅ Evaluation finished.")

if __name__ == "__main__":
    main()

