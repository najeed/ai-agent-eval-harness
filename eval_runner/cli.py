"""
cli.py

Main entry point for the Evaluation Harness CLI.
Updated for modularity and plugin-based extensibility with argument groups.
"""

import argparse
import asyncio
import sys
import os
import json
from pathlib import Path
from . import loader
from . import engine
from . import reporter
from . import plugins

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI Agent Evaluation Harness (OpenCore)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Subparsers for different commands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # --- EVALUATE COMMAND ---
    eval_parser = subparsers.add_parser("evaluate", help="Run evaluation on scenarios")
    eval_parser.add_argument(
        "--path", required=True, help="Path to scenario file or directory"
    )
    eval_parser.add_argument(
        "--format", default="jsonl", choices=["jsonl", "csv"], help="Dataset format"
    )
    eval_parser.add_argument(
        "--output", default="reports/latest_results.json", help="Path to save results"
    )
    eval_parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose logging"
    )
    eval_parser.add_argument(
        "--limit", type=int, help="Limit the number of scenarios to run"
    )
    
    # Plugin Argument Groups: Provide a dedicated space for plugins to add their args
    # We pass the eval_parser to plugins so they can add their own argument groups
    plugins.manager.trigger("extend_cli", eval_parser)
    
    # --- INIT COMMAND ---
    subparsers.add_parser("init", help="Initialize a new evaluation project")
    
    # --- LIST-METRICS COMMAND ---
    subparsers.add_parser("list-metrics", help="List registered evaluation metrics")

    # --- SPEC-TO-EVAL COMMAND ---
    spec_parser = subparsers.add_parser("spec-to-eval", help="Convert Markdown PRD to Scenario JSON")
    spec_parser.add_argument("--input", required=True, help="Path to Markdown PRD")
    spec_parser.add_argument("--output", help="Output JSON path (optional)")

    args = parser.parse_args()

    if args.command == "evaluate":
        asyncio.run(run_evaluate(args))
    elif args.command == "init":
        handle_init(args)
    elif args.command == "list-metrics":
        from . import metrics
        print("\nRegistered Metrics:")
        for name in metrics.MetricRegistry._metrics.keys():
            print(f" - {name}")
    elif args.command == "spec-to-eval":
        handle_spec_to_eval(args)
    else:
        parser.print_help()

async def run_evaluate(args):
    """Execution logic for the 'evaluate' command."""
    print(f"\n[CLI] Loading scenarios from: {args.path}")
    
    try:
        path_obj = Path(args.path)
        scenarios = loader.load_dataset(path_obj, format_type=args.format if args.format != "jsonl" else None)
    except Exception as e:
        print(f"[CLI] Error loading dataset: {e}")
        sys.exit(1)

    if args.limit:
        scenarios = scenarios[:args.limit]

    print(f"[CLI] Running {len(scenarios)} scenarios...")
    
    all_results = []
    for i, scenario in enumerate(scenarios):
        print(f"\n[{i+1}/{len(scenarios)}] Scenario: {scenario.get('title', 'Untitled')}")
        results = await engine.run_evaluation(scenario)
        all_results.extend(results)
        
        # Use the standard reporter to print results for each scenario
        reporter.generate_report(scenario, results, export_trajectory=True)

def detect_framework():
    """Simple heuristic to detect the agent framework used in the current dir."""
    cwd = Path.cwd()
    if (cwd / "langgraph.json").exists() or (cwd / "nodes.py").exists():
        return "LangGraph"
    if (cwd / "crew.py").exists() or (cwd / "agents.yaml").exists():
        return "CrewAI"
    
    # Check requirements.txt
    req_path = cwd / "requirements.txt"
    if req_path.exists():
        content = req_path.read_text().lower()
        if "langgraph" in content: return "LangGraph"
        if "crewai" in content: return "CrewAI"
        
    return "Custom"

def list_industries():
    """Mock list of supported industries for scaffolding."""
    return ["accounting", "telecom", "healthcare", "legal", "generic"]

def handle_init(_):
    """Wizard for initializing a new evaluation project."""
    print("\n--- OpenCore Scaffolding Wizard ---")
    framework = detect_framework()
    print(f"Detected Framework: {framework}")
    
    industries = list_industries()
    print("\nAvailable Industries:")
    for i, ind in enumerate(industries):
        print(f"{i+1}. {ind}")
    
    choice = input("\nSelect industry (number): ").strip()
    try:
        industry = industries[int(choice)-1]
    except:
        industry = "generic"
        
    api_url = input("Agent API URL (default: http://localhost:5001/execute_task): ").strip()
    if not api_url:
        api_url = "http://localhost:5001/execute_task"
        
    # Generate eval_config.json
    config = {
        "project_name": "My AI Agent Eval",
        "industry": industry,
        "framework": framework,
        "agent_api_url": api_url
    }
    
    config_path = Path("eval_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    # Create scenarios dir
    scenario_dir = Path("scenarios")
    scenario_dir.mkdir(parents=True, exist_ok=True)
    
    starter = {
        "scenario_id": f"starter_{industry}",
        "title": f"Starter Scenario ({industry})",
        "industry": industry,
        "tasks": [{"task_id": "t1", "description": "Verify agent can greet."}]
    }
    
    with open(scenario_dir / "starter_scenario.json", "w") as f:
        json.dump(starter, f, indent=2)
        
    print(f"\n[CLI] Project initialized successfully!")
    print(f"[CLI] Created: eval_config.json, scenarios/starter_scenario.json")

def handle_spec_to_eval(args):
    """Handler for 'spec-to-eval' command."""
    from . import spec_parser
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"â Œ Error: Markdown file not found at {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    scenario = spec_parser.parse_markdown_to_scenario(md_content)
    
    # Determine default output path if not provided
    if args.output:
        output_path = Path(args.output)
    else:
        # industries/[industry]/scenarios/[scenario_id].json
        industry = scenario.get("industry", "generic")
        scenario_id = scenario.get("scenario_id", "new_scenario")
        output_path = Path("industries") / industry / "scenarios" / f"{scenario_id}.json"

    spec_parser.save_scenario_stub(scenario, output_path)
    print(f"âœ… Successfully converted {input_path} to {output_path}")

if __name__ == "__main__":
    main()
