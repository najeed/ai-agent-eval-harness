"""
cli.py

This module implements the Command Line Interface (CLI) for the AI Agent Evaluation Harness.
It provides commands for configuring evaluations (init) and running them (run).
"""

import argparse
import json
import os
import sys
import asyncio
from pathlib import Path
from . import loader
from . import engine
from . import reporter

def detect_framework():
    """
    Attempts to detect the agent framework in the current directory.
    Returns: 'LangGraph', 'CrewAI', or 'Custom'
    """
    cwd = Path.cwd()
    
    # LangGraph signals
    if (cwd / "langgraph.json").exists() or (cwd / "nodes.py").exists():
        return "LangGraph"
    
    # CrewAI signals
    if (cwd / "crew.py").exists() or (cwd / "agents.yaml").exists() or (cwd / "config" / "agents.yaml").exists():
        return "CrewAI"
    
    # Dependency check
    reqs = cwd / "requirements.txt"
    if reqs.exists():
        try:
            content = reqs.read_text().lower()
            if "langgraph" in content:
                return "LangGraph"
            if "crewai" in content:
                return "CrewAI"
        except Exception:
            pass
            
    return "Custom"

def list_industries():
    """Returns a list of available industries from the harness."""
    harness_root = Path(__file__).parent.parent
    industries_dir = harness_root / "industries"
    if industries_dir.exists():
        return sorted([d.name for d in industries_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
    return ["accounting", "aerospace", "agriculture", "airline", "telecom"]

def handle_init(args):
    """Onboarding wizard to initialize an evaluation configuration."""
    print("\n🚀 AI Agent Evaluation Harness - Initialization Wizard\n")
    
    framework = detect_framework()
    print(f"[*] Detected Framework: {framework}")
    
    industries = list_industries()
    print("\nAvailable Industries:")
    for idx, ind in enumerate(industries, 1):
        print(f"  {idx:2d}. {ind}")
    
    try:
        choice = input(f"\nSelect industry (1-{len(industries)}, default 1): ").strip()
        industry_idx = int(choice) - 1 if choice else 0
        if not (0 <= industry_idx < len(industries)):
            industry_idx = 0
    except (ValueError, IndexError):
        industry_idx = 0
    
    selected_industry = industries[industry_idx]
    
    api_url = input("\nEnter Agent API URL (default: http://localhost:5001/execute_task): ").strip()
    if not api_url:
        api_url = "http://localhost:5001/execute_task"
        
    config = {
        "industry": selected_industry,
        "agent_api_url": api_url,
        "framework": framework,
        "version": "1.0.0"
    }
    
    with open("eval_config.json", "w") as f:
        json.dump(config, f, indent=2)
    
    Path("scenarios").mkdir(exist_ok=True)
    
    starter_scenario = {
        "scenario_id": f"starter_{selected_industry}_1",
        "title": f"Starter {selected_industry.capitalize()} Scenario",
        "description": "Initial test scenario created by onboarding CLI.",
        "use_case": "General Evaluation",
        "core_function": "Initial Setup",
        "industry": selected_industry,
        "tasks": [
            {
                "task_id": "task_1",
                "description": "Perform a basic diagnostic action.",
                "expected_outcome": "Success",
                "success_criteria": [
                    {"metric": "tool_call_correctness", "threshold": 1.0}
                ]
            }
        ]
    }
    
    with open(Path("scenarios") / "starter_scenario.json", "w") as f:
        json.dump(starter_scenario, f, indent=2)
        
    print(f"\n✅ Created eval_config.json for {selected_industry}")
    print(f"✅ Created scenarios/starter_scenario.json")
    print("\nNext steps:")
    print("  1. Update scenarios/starter_scenario.json with your actual tasks.")
    print("  2. Run 'eval-harness run' to start evaluation.\n")

async def run_evaluation_flow(args):
    """Executes the evaluation flow derived from the original __main__.py logic."""
    industry = args.industry
    scenario_parts = args.scenario
    
    # If no industry provided, try to load from config
    if not industry and Path("eval_config.json").exists():
        with open("eval_config.json", "r") as f:
            config = json.load(f)
            industry = config.get("industry")
            print(f"[*] Using industry '{industry}' from eval_config.json")

    if not industry:
        print("Error: Industry must be specified via --industry or in eval_config.json")
        return

    print(f"Starting evaluation for industry '{industry}'...")

    base_path = Path(__file__).parent.parent / "industries"
    scenarios_to_run = []

    for scenario_path_part in scenario_parts:
        full_path = base_path / industry / "scenarios" / scenario_path_part
        if scenario_path_part == "all":
            full_path = base_path / industry / "scenarios"
            
        if not full_path.exists():
            # Try local scenarios dir if it exists
            local_path = Path("scenarios") / scenario_path_part
            if local_path.exists():
                full_path = local_path
            else:
                print(f"Warning: Path not found, skipping: {full_path}")
                continue

        if full_path.is_dir():
            print(f"Found directory: {full_path}. Searching for scenarios...")
            json_files = sorted(full_path.rglob("*.json"))
            scenarios_to_run.extend(json_files)
        elif full_path.is_file() and full_path.suffix == ".json":
            scenarios_to_run.append(full_path)

    scenarios_to_run = sorted(list(set(scenarios_to_run)))

    if not scenarios_to_run:
        print(f"Error: No valid scenario files found to run.")
        return

    print(f"Discovered {len(scenarios_to_run)} total scenario(s) to run.")

    loaded_scenarios = []
    for scenario_path in scenarios_to_run:
        try:
            scenario_data = loader.load_scenario(scenario_path)
            loaded_scenarios.append({"path": scenario_path, "data": scenario_data})
        except Exception as e:
            print(f"Error loading scenario {scenario_path}: {e}")

    print(f"Successfully loaded {len(loaded_scenarios)} scenarios.")

    print("\n" + "#" * 80)
    print("Running evaluation engine concurrently...")
    print("#" * 80)

    tasks = [engine.run_evaluation(item["data"]) for item in loaded_scenarios]
    results_list = await asyncio.gather(*tasks)
    
    print("Engine runs complete.")

    for item, results in zip(loaded_scenarios, results_list):
        print("\n" + "#" * 80)
        try:
            display_path = item['path'].relative_to(base_path)
        except ValueError:
            display_path = item['path']
        print(f"REPORT FOR: {display_path}")
        print("#" * 80)
        reporter.generate_report(item["data"], results)

    print("\n" + "=" * 80)
    print("✅ ALL EVALUATIONS FINISHED.")
    print("=" * 80 + "\n")

def main():
    parser = argparse.ArgumentParser(prog="eval-harness", description="AI Agent Evaluation Harness CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # init
    subparsers.add_parser("init", help="Initialize evaluation config in current directory")
    
    # run
    run_parser = subparsers.add_parser("run", help="Run evaluation engine")
    run_parser.add_argument("--industry", help="The industry to evaluate")
    run_parser.add_argument("--scenario", nargs="+", default=["all"], help="Scenario files or directories to run")
    run_parser.add_argument("--config", default="eval_config.json", help="Path to evaluation config")

    args = parser.parse_args()
    
    if args.command == "init":
        handle_init(args)
    elif args.command == "run":
        asyncio.run(run_evaluation_flow(args))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
