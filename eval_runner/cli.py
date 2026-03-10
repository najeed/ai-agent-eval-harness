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
    
    # --- AES COMMAND ---
    aes_parser = subparsers.add_parser("aes", help="Agent Eval Specification (AES) utilities")
    aes_subparsers = aes_parser.add_subparsers(dest="aes_command", help="AES subcommands")
    
    validate_parser = aes_subparsers.add_parser("validate", help="Validate an AES benchmark file")
    validate_parser.add_argument("path", help="Path to .aes.yaml file or directory")

    # --- REPLAY COMMAND ---
    replay_parser = subparsers.add_parser("replay", help="Replay an agent execution from run.jsonl")
    replay_parser.add_argument("path", help="Path to run.jsonl file")

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
    elif args.command == "import-drift":
        handle_import_drift(args)
    elif args.command == "aes":
        if args.aes_command == "validate":
            handle_aes_validate(args)
    elif args.command == "replay":
        handle_replay(args)
    else:
        parser.print_help()

def handle_aes_validate(args):
    """Handler for 'aes validate' command."""
    import yaml
    import jsonschema
    from pathlib import Path

    schema_path = Path(__file__).parent.parent / "spec" / "aes" / "aes.schema.json"
    if not schema_path.exists():
        print(f"❌ Error: AES schema not found at {schema_path}")
        return

    with open(schema_path, "r") as f:
        schema = json.load(f)

    path = Path(args.path)
    files = []
    if path.is_dir():
        files = list(path.glob("*.aes.yaml"))
    else:
        files = [path]

    if not files:
        print(f"❌ No .aes.yaml files found at {path}")
        return

    for file_path in files:
        try:
            with open(file_path, "r") as f:
                data = yaml.safe_load(f)
            
            jsonschema.validate(instance=data, schema=schema)
            print(f"✅ {file_path.name}: Valid")
        except jsonschema.exceptions.ValidationError as e:
            print(f"❌ {file_path.name}: Invalid")
            print(f"   Reason: {e.message}")
        except Exception as e:
            print(f"❌ {file_path.name}: Error: {e}")

def handle_replay(args):
    """Handler for 'replay' command."""
    print(f"\n[Replay] Reconstructing execution from: {args.path}")
    path = Path(args.path)
    if not path.exists():
        print(f"❌ Error: Replay file not found at {path}")
        return

    with open(path, "r") as f:
        for line in f:
            event = json.loads(line)
            ev_type = event.get("event", "unknown")
            timestamp = event.get("timestamp", "")
            
            if ev_type == "run_start":
                print(f"--- Run Started: {event.get('run_id')} ({event.get('scenario')}) ---")
            elif ev_type == "prompt":
                role = event.get("role", "user")
                content = event.get("content", "")
                print(f"[{role.upper()}]: {content}")
            elif ev_type == "agent_response":
                step = event.get("step")
                content = event.get("content", "")
                print(f"Agent (Step {step}): {content}")
            elif ev_type == "tool_call":
                tool = event.get("tool")
                args_val = event.get("arguments")
                print(f"🔧 Tool Call: {tool}({args_val})")
            elif ev_type == "tool_result":
                tool = event.get("tool")
                result = event.get("result")
                print(f"📥 Tool Result ({tool}): {result}")
            elif ev_type == "evaluation":
                metric = event.get("metric")
                value = event.get("value")
                print(f"📊 Metric: {metric} = {value}")
            elif ev_type == "run_end":
                status = event.get("status")
                print(f"--- Run Finished: {status} ---")

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
        
        # Apply Triage to results
        from . import triage
        triage.TriageEngine.apply_triage(results)
        
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

def handle_import_drift(args):
    """Handler for 'import-drift' command."""
    from . import drift_importer
    input_path = Path(args.input)
    industry = args.industry
    output_dir = Path(args.output_dir) if args.output_dir else Path("industries") / industry / "scenarios"
    
    try:
        output_file = drift_importer.import_trace_as_scenario(input_path, industry, output_dir)
        print(f"âœ… Successfully imported drift from {input_path} to {output_file}")
    except Exception as e:
        print(f"â Œ Error importing drift: {e}")

if __name__ == "__main__":
    main()
