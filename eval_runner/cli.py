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
from . import catalog
from . import linter
from . import doctor
from . import triage
from . import config

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
    eval_parser.add_argument(
        "--attempts", type=int, default=1, help="Number of attempts per scenario (for pass@k)"
    )
    eval_parser.add_argument(
        "--run-log-dir", help="Directory for run trace logs (overrides RUN_LOG_DIR)"
    )
    eval_parser.add_argument(
        "--per-run-logs", action="store_true", default=None, help="Save individual .jsonl for each run"
    )
    eval_parser.add_argument(
        "--master-log", action="store_true", default=None, help="Append all events to a master run.jsonl"
    )
    eval_parser.add_argument(
        "--protocol", default="http", choices=["http", "local", "socket"], help="Communication protocol for the agent"
    )
    eval_parser.add_argument(
        "--agent-cmd", help="Command to run the local agent (for protocol=local)"
    )
    eval_parser.add_argument(
        "--agent-socket", help="Socket address (unix:/path or tcp:host:port) (for protocol=socket)"
    )
    
    # --- LIST COMMAND ---
    list_parser = subparsers.add_parser("list", help="List and search available scenarios")
    list_parser.add_argument(
        "--search", help="Search query for filtering scenarios"
    )
    list_parser.add_argument(
        "--refresh", action="store_true", help="Rebuild the scenario index"
    )

    # --- LINT COMMAND ---
    lint_parser = subparsers.add_parser("lint", help="Verify scenario quality and AES compliance")
    lint_parser.add_argument("path", help="Path to scenario file or directory")
    
    # Security Guardrails: Command Hijacking Prevention
    # Removed `extend_cli` hook. Plugins must register via namespaced registry `eval-harness plugin <name>`
    
    # --- AES COMMAND ---
    aes_parser = subparsers.add_parser("aes", help="Agent Eval Specification (AES) utilities")
    aes_subparsers = aes_parser.add_subparsers(dest="aes_command", help="AES subcommands")
    
    validate_parser = aes_subparsers.add_parser("validate", help="Validate an AES benchmark file")
    validate_parser.add_argument("path", help="Path to .aes.yaml file or directory")

    # --- SPEC-TO-EVAL COMMAND ---
    spec_parser = subparsers.add_parser("spec-to-eval", help="Convert Markdown PRD/Spec to Scenario JSON")
    spec_parser.add_argument("--input", required=True, help="Path to .md file")
    spec_parser.add_argument("--output", help="Path to save generated .json")

    # --- AUTO-TRANSLATE COMMAND ---
    trans_parser = subparsers.add_parser("auto-translate", help="Translate raw documents to JSON via a local LLM (Ollama required)")
    trans_parser.add_argument("--input", required=True, help="Path to the source document")
    trans_parser.add_argument("--model", default="llama3", help="Local Ollama model to use (Ollama must be running)")
    trans_parser.add_argument("--industry", help="Target industry folder override")
    trans_parser.add_argument("--output", help="Explicit path to save the generated JSON")

    # --- IMPORT-DRIFT COMMAND ---
    drift_parser = subparsers.add_parser("import-drift", help="Import production traces as scenarios")
    drift_parser.add_argument("--input", required=True, help="Path to trace file")
    drift_parser.add_argument("--industry", required=True, help="Industry category")
    drift_parser.add_argument("--output-dir", help="Directory to save scenarios")

    # --- DOCTOR COMMAND ---
    subparsers.add_parser("doctor", help="Check environment and dependencies")

    # --- CONSOLE COMMAND ---
    console_parser = subparsers.add_parser("console", help="Launch the Web Admin Console (REST API & Frontend server)")
    console_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind to")
    console_parser.add_argument("--port", type=int, default=5000, help="Port to serve the console API on")

    # --- QUICKSTART COMMAND ---
    subparsers.add_parser("quickstart", help="Run a 60-second demo (spawns agent + runs eval)")

    # --- REPORT COMMAND ---
    report_parser = subparsers.add_parser("report", help="Generate HTML report from a run trace")
    report_parser.add_argument("path", help="Path to run.jsonl file")

    # --- SCENARIO COMMAND ---
    scenario_parser = subparsers.add_parser("scenario", help="Scenario management utilities")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_command")
    scenario_sub.add_parser("generate", help="Interactively generate new test scenarios")

    # --- RECORD COMMAND ---
    record_parser = subparsers.add_parser("record", help="Record interactions with an agent")
    record_parser.add_argument("--agent", default=config.AGENT_API_URL, help="Agent entry point URL")

    # --- PLAYGROUND COMMAND ---
    playground_parser = subparsers.add_parser("playground", help="Interactive REPL to experiment with an agent")
    playground_parser.add_argument("--agent", default="http://localhost:5001/execute_task", help="Agent API URL")

    # --- EXPORT COMMAND ---
    export_p = subparsers.add_parser("export", help="Export run traces to external formats (e.g., HuggingFace)")
    export_p.add_argument("--input", required=True, help="Path to run.jsonl trace")
    export_p.add_argument("--format", default="hf", choices=["hf"], help="Target format")
    export_p.add_argument("--output", required=True, help="Path to save exported dataset")
    
    # --- MUTATE COMMAND ---
    mutate_parser = subparsers.add_parser("mutate", help="Generate adversarial scenario variants")
    mutate_parser.add_argument("--input", required=True, help="Path to input scenario JSON")
    mutate_parser.add_argument("--type", required=True, choices=["typo", "injection", "ambiguity"], help="Type of mutation to apply")
    mutate_parser.add_argument("--output", help="Path to save mutated scenario")
    
    # --- REPLAY COMMAND ---
    replay_parser = subparsers.add_parser("replay", help="Replay a run trace (Flight Recorder)")
    replay_parser.add_argument("--path", default="runs/run.jsonl", help="Path to the trace file to replay")

    # --- CLEANUP-RUNS COMMAND ---
    cleanup_parser = subparsers.add_parser("cleanup-runs", help="Housekeeping: Remove old trace files")
    cleanup_parser.add_argument("--days", type=int, default=7, help="Remove files older than N days")
    cleanup_parser.add_argument("--force", action="store_true", help="Skip confirmation")

    # --- INSTALL COMMAND ---
    install_parser = subparsers.add_parser("install", help="Install curated scenario packs")
    install_parser.add_argument("pack", help="Name of the pack (e.g., telecom-pack, finance-pack)")

    # --- ANALYZE COMMAND ---
    analyze_parser = subparsers.add_parser("analyze", help="Scan GitHub repo to auto-generate scenarios")
    analyze_parser.add_argument("url", help="GitHub repository URL")

    # --- CI COMMAND ---
    ci_parser = subparsers.add_parser("ci", help="CI/CD utility commands")
    ci_subparsers = ci_parser.add_subparsers(dest="ci_command")
    ci_subparsers.add_parser("generate", help="Scaffold a .github/workflows/agent_eval.yml file")

    # --- FAILURES COMMAND ---
    failures_parser = subparsers.add_parser("failures", help="Failure Corpus utilities")
    failures_subparsers = failures_parser.add_subparsers(dest="failures_command")
    search_parser = failures_subparsers.add_parser("search", help="Search the failure corpus for edge cases")
    search_parser.add_argument("query", help="Search term (e.g., 'pii', 'timeout')")

    # --- EXPLAIN COMMAND ---
    explain_parser = subparsers.add_parser("explain", help="Analyze trace logs to diagnose root causes")
    explain_parser.add_argument("path", help="Path to run.jsonl file")

    # --- PLUGIN COMMAND ---
    # Security Guardrails: Strictly Namespaced Automated Registry
    plugin_parser = subparsers.add_parser("plugin", help="Execute plugin-specific subcommands")
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_name", help="Plugin namespace")

    class CommandRegistry:
        def __init__(self, parser):
            self.parser = parser
            self.handlers = {}
            
        def register_command(self, name: str, handler, help_text: str = ""):
            sub = self.parser.add_parser(name, help=help_text)
            self.handlers[name] = handler
            return sub

    plugin_handlers = {}
    for plugin in plugins.manager.plugins:
        if hasattr(plugin, "on_register_commands"):
            plugin_id = plugin.__class__.__name__.lower().replace("plugin", "")
            p_subparser = plugin_subparsers.add_parser(plugin_id, help=f"Commands for {plugin_id}")
            cmd_subparsers = p_subparser.add_subparsers(dest="plugin_cmd")
            registry = CommandRegistry(cmd_subparsers)
            
            plugin.on_register_commands(registry)
            
            if registry.handlers:
                plugin_handlers[plugin_id] = registry.handlers

    args = parser.parse_args()

    try:
        if args.command == "evaluate":
            asyncio.run(run_evaluate(args))
        elif args.command == "list":
            handle_list(args)
        elif args.command == "lint":
            handle_lint(args)
        elif args.command == "init":
            handle_init(args)
        elif args.command == "list-metrics":
            from . import metrics
            print("\nRegistered Metrics:")
            for name in metrics.MetricRegistry._metrics.keys():
                print(f" - {name}")
        elif args.command == "spec-to-eval":
            handle_spec_to_eval(args)
        elif args.command == "auto-translate":
            asyncio.run(handle_auto_translate(args))
        elif args.command == "import-drift":
            handle_import_drift(args)
        elif args.command == "aes":
            if args.aes_command == "validate":
                handle_aes_validate(args)
        elif args.command == "replay":
            handle_replay(args)
        elif args.command == "mutate":
            handle_mutate(args)
        elif args.command == "run":
            asyncio.run(run_scenario(args))
        elif args.command == "console":
            from .console.app import run_server
            print(f"\n[CLI] Starting Admin Console API on http://{args.host}:{args.port}")
            run_server(host=args.host, port=args.port)
        elif args.command == "doctor":
            from . import doctor
            asyncio.run(doctor.run_doctor())
        elif args.command == "quickstart":
            from . import quickstart
            asyncio.run(quickstart.run_quickstart())
        elif args.command == "report":
            handle_report(args)
        elif args.command == "scenario":
            if args.scenario_command == "generate":
                from . import scaffold
                scaffold.generate_interactive()
        elif args.command == "record":
            from . import trace_recorder
            asyncio.run(trace_recorder.record_interaction(args.agent))
        elif args.command == "playground":
            from . import playground
            asyncio.run(playground.run_playground(args.agent))
        elif args.command == "export":
            handle_export(args)
        elif args.command == "cleanup-runs":
            handle_cleanup_runs(args)
        elif args.command == "install":
            handle_install(args)
        elif args.command == "analyze":
            asyncio.run(handle_analyze(args))
        elif args.command == "ci":
            if args.ci_command == "generate":
                handle_ci_generate(args)
        elif args.command == "failures":
            if args.failures_command == "search":
                handle_failures_search(args)
        elif args.command == "explain":
            handle_explain(args)
        elif args.command == "plugin":
            if args.plugin_name in plugin_handlers and args.plugin_cmd in plugin_handlers[args.plugin_name]:
                handler = plugin_handlers[args.plugin_name][args.plugin_cmd]
                handler(args)
            else:
                print("Invalid or missing plugin command.")
        else:
            parser.print_help()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

def handle_list(args):
    """Handler for 'list' command."""
    cat = catalog.ScenarioCatalog()
    if args.refresh:
        print("[Catalog] Rebuilding index...")
        cat.build_index()
    else:
        cat.load_index()
    
    catalog.list_scenarios(args.search)

def handle_lint(args):
    """Handler for 'lint' command."""
    linter.run_lint(args.path)

def reconstruct_results_from_events(events: list) -> list:
    """
    Reconstructs the task results structure from a list of JSONL event dictionaries.
    Required for generating reports from historical traces.
    """
    results_map = {}
    
    # 1. Group events by task_id and capture metrics
    for event in events:
        task_id = event.get("task_id", "unknown")
        ev_type = event.get("event")
        
        if task_id not in results_map:
            results_map[task_id] = {
                "task_id": task_id,
                "metrics": [],
                "conversation_history": [],
                "triage_tag": "SUCCESS"
            }
        
        res = results_map[task_id]
        
        if ev_type == "evaluation":
            res["metrics"].append({
                "metric": event.get("metric"),
                "score": event.get("value"),
                "threshold": event.get("threshold", 0.5),
                "success": event.get("success", False)
            })
        elif ev_type in ["prompt", "agent_response", "tool_result", "agent_request"]:
            # Reconstruct history for Mermaid visualization
            role = "agent" if ev_type in ["agent_response", "agent_request"] else "user"
            if ev_type == "tool_result": role = "environment"
            
            res["conversation_history"].append({
                "role": role,
                "content": event.get("content") or {"action": event.get("tool"), "status": event.get("status")}
            })

    # 2. Finalize triage and structure
    from .triage import TriageEngine
    final_results = list(results_map.values())
    TriageEngine.apply_triage(final_results)
    
    return final_results

def handle_report(args):
    """Handler for 'report' command."""
    from . import reporter
    print(f"\n[Report] Generating HTML report from: {args.path}")
    path = Path(args.path)
    if not path.exists():
        print(f"❌ Error: Trace file not found at {path}")
        return

    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
    except Exception as e:
        print(f"❌ Error reading trace: {e}")
        return
    
    run_start = next((e for e in events if e.get("event") == "run_start"), None)
    if not run_start:
        print("❌ Error: Could not find run_start event in trace.")
        return
        
    scenario_metadata = run_start.get("metadata", {})
    scenario_id = run_start.get("scenario", "unknown")
    
    # Reconstruct scenario object for the reporter
    scenario = {
        "scenario_id": scenario_id,
        "title": scenario_metadata.get("title", f"Report: {scenario_id}"),
        "industry": scenario_metadata.get("industry", "N/A"),
        "description": scenario_metadata.get("description", "")
    }
    
    print("   -> Reconstructing task results from trace...")
    results = reconstruct_results_from_events(events)
    
    if not results:
        print("⚠ Warning: No task results found in trace.")
        return

    print("   -> Generating Premium HTML Report...")
    html_path = reporter.generate_html_report(scenario, results)
    print(f"✔ HTML Report generated successfully: {html_path}")

def handle_aes_validate(args):
    """Handler for 'aes validate' command."""
    import yaml
    import jsonschema
    from pathlib import Path

    schema_path = Path(__file__).parent.parent / "spec" / "aes" / "aes.schema.json"
    if not schema_path.exists():
        print(f"[ERROR] AES schema not found at {schema_path}")
        return

    with open(schema_path, "r") as f:
        schema = json.loads(f.read())

    path = Path(args.path)
    files = []
    if path.is_dir():
        files = list(path.glob("*.aes.yaml"))
    else:
        files = [path]

    if not files:
        print(f"[FAIL] No .aes.yaml files found at {path}")
        return

    for file_path in files:
        try:
            with open(file_path, "r") as f:
                data = yaml.safe_load(f)
            
            jsonschema.validate(instance=data, schema=schema)
            print(f"[OK] {file_path.name}: Valid")
        except jsonschema.exceptions.ValidationError as e:
            print(f"[FAIL] {file_path.name}: Invalid")
            print(f"   Reason: {e.message}")
        except Exception as e:
            print(f"[ERROR] {file_path.name}: {e}")

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

async def run_scenario(args):
    """Loads a scenario and executes the evaluation."""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file {scenario_path} not found.")
        return

    try:
        scenario = loader.load_scenario(scenario_path)
        results = await engine.run_evaluation(scenario, attempts=args.attempts, metadata={"args": args})
        
        # Determination of results is handled by the runner and ReportingPlugin handles the output.
        print(f"\n   [CLI] Evaluation complete for {scenario_path.name}")
    except Exception as e:
        print(f"Error during evaluation: {e}")
        import traceback
        traceback.print_exc()

async def run_evaluate(args):
    """Execution logic for the 'evaluate' command."""
    # Set run-log environment variables from flags
    if args.run_log_dir:
        os.environ["RUN_LOG_DIR"] = args.run_log_dir
    if args.per_run_logs is not None:
        os.environ["RUN_LOG_PER_RUN"] = "true" if args.per_run_logs else "false"
    if args.master_log is not None:
        os.environ["RUN_LOG_MASTER"] = "true" if args.master_log else "false"
    
    if args.protocol == "local" and args.agent_cmd:
        os.environ["AGENT_LOCAL_CMD"] = args.agent_cmd
    if args.protocol == "socket" and args.agent_socket:
        os.environ["AGENT_SOCKET_ADDR"] = args.agent_socket

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
    research_summary = {}

    for i, scenario in enumerate(scenarios):
        attempts = getattr(args, "attempts", 1)
        scenario_tries = []
        
        for attempt in range(attempts):
            print(f"\n[{i+1}/{len(scenarios)}] Attempt {attempt+1}/{attempts} - Scenario: {scenario.get('title', 'Untitled')}")
            # Ensure protocol is passed to engine
            results = await engine.run_evaluation(scenario, metadata={
                "args": args,
                "protocol": args.protocol
            })
            scenario_tries.append(results)
            
            # Results are now handled by ReportingPlugin via engine hooks
            # triage.TriageEngine.apply_triage(results) is still relevant but should also be a plugin?
            # For now, let's keep it here or move it to a TriagePlugin.
            pass
        
        # Calculate pass@k and Consistency if multiple attempts
        if attempts > 1:
            success_flags = [all(all(m["success"] for m in tr["metrics"]) for tr in tries) for tries in scenario_tries]
            successes = sum(1 for f in success_flags if f)
            pass_at_k = 1.0 if successes > 0 else 0.0
            
            # Outcome Stability (Consistency)
            # 1. Success Consistency: are the results stable (all pass or all fail)?
            success_consistency = successes / attempts if successes > attempts / 2 else (attempts - successes) / attempts
            
            # 2. Semantic Consistency: do the summaries agree?
            from . import metrics
            summaries = []
            for tries in scenario_tries:
                if not tries: continue
                # Get the summary from the last task's last agent response
                history = tries[-1].get("conversation_history", [])
                if history:
                    last_msg = history[-1]
                    if last_msg.get("role") == "agent":
                        content = last_msg.get("content", {})
                        if isinstance(content, dict):
                            summaries.append(content.get("summary") or content.get("content") or str(content))
                        else:
                            summaries.append(str(content))
            
            semantic_consistency = metrics.calculate_consensus_scoring(summaries) if len(summaries) > 1 else 1.0
            
            print(f"   - Semantic Stability: {semantic_consistency:.2f}")
            
            research_summary[scenario.get("scenario_id")] = {
                "title": scenario.get("title"),
                "attempts": attempts,
                "successes": successes,
                "pass_at_k": pass_at_k,
                "success_consistency": success_consistency,
                "semantic_stability": semantic_consistency
            }
            
        all_results.extend([res for tries in scenario_tries for res in tries])

    # Save research summary if multiple attempts were made
    if research_summary:
        summary_path = Path("reports/research_summary.json")
        summary_path_md = Path("reports/research_summary.md")
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(summary_path, "w") as f:
            json.dump(research_summary, f, indent=2)
            
        print("\n" + "=" * 80)
        print(f"{'SCENARIO ID':<25} | {'PASS@K':<10} | {'STABILITY':<12} | {'SEMANTIC':<10}")
        print("-" * 80)
        
        md_content = ["# Research Evaluation Summary", "", "| Scenario ID | Pass@k | Success Consistency | Semantic Stability |", "| :--- | :--- | :--- | :--- |"]
        
        for k, v in research_summary.items():
            pass_k = f"{v['pass_at_k']*100:.1f}%"
            stab = f"{v['success_consistency']*100:.1f}%"
            sem = f"{v['semantic_stability']:.2f}"
            print(f"{k[:25]:<25} | {pass_k:<10} | {stab:<12} | {sem:<10}")
            md_content.append(f"| {k} | {pass_k} | {stab} | {sem} |")
            
        print("=" * 80)
        
        with open(summary_path_md, "w") as f:
            f.write("\n".join(md_content))
            
        print(f"\n[Research] Summary saved to {summary_path} and {summary_path_md}")

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
        api_url = config.AGENT_API_URL
        
    # Generate eval_config.json
    scaffold_config = {
        "project_name": "My AI Agent Eval",
        "industry": industry,
        "framework": framework,
        "agent_api_url": api_url
    }
    
    config_path = Path("eval_config.json")
    with open(config_path, "w") as f:
        json.dump(scaffold_config, f, indent=2)
    
    # Create agent_adapter.py template
    adapter_content = """import asyncio
import aiohttp

async def call_custom_agent(payload: dict):
    # Implement your agent calling logic here
    # return {"action": "final_answer", "summary": "Done"}
    pass

if __name__ == "__main__":
    print("Agent Adapter Template Ready.")
"""
    with open("agent_adapter.py", "w") as f:
        f.write(adapter_content)

    # Create README.md
    readme_content = f"""# {config['project_name']}
    
Evaluation suite for {framework} agent in the {industry} industry.

## How to run
1. Start your agent
2. Run `eval-harness evaluate --path scenarios/`
"""
    with open("README.md", "w") as f:
        f.write(readme_content)

    # Create scenarios dir
    scenario_dir = Path("scenarios")
    scenario_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine expected dataset path based on the industry
    expected_csv = "orders.csv" if industry == "ecommerce" else "appointments.csv" if industry == "healthcare" else "support_tickets.csv" if industry == "telecom" else f"{industry}_records.csv"
    
    starter = {
        "scenario_id": f"starter_{industry}",
        "title": f"Starter Scenario ({industry})",
        "industry": industry,
        "dataset": {
            "path": f"industries/{industry}/datasets/{expected_csv}",
            "format": "csv"
        },
        "tasks": [{"task_id": "t1", "description": "Verify agent can greet."}]
    }
    
    with open(scenario_dir / "starter_scenario.json", "w") as f:
        json.dump(starter, f, indent=2)
        
    print(f"\n[CLI] Project initialized successfully!")
    print(f"[CLI] Created: eval_config.json, scenarios/starter_scenario.json")

async def handle_auto_translate(args):
    """Handler for 'auto-translate' command."""
    from . import auto_translate
    input_path = Path(args.input)
    
    if not input_path.exists():
        print(f"[FAIL] Error: Document not found at {input_path}")
        return
        
    print("\n[Auto-Translate] NOTE: This utility requires a local LLM (Ollama) to be running.")
    print(f"[Auto-Translate] Reading {input_path.name}...")
    try:
        text = auto_translate.extract_text(input_path)
    except Exception as e:
        print(f"[FAIL] Error extracting text: {e}")
        return
        
    print(f"[Auto-Translate] Prompting Ollama model '{args.model}' (this may take a minute)...")
    try:
        scenario = await auto_translate.translate_to_scenario(text, model=args.model)
    except Exception as e:
        print(f"[FAIL] Translation failed: {e}")
        return
        
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        industry = args.industry or scenario.get("industry", "generic").lower().replace(" ", "_")
        scenario_id = scenario.get("scenario_id", "auto-translated")
        output_path = Path("industries") / industry / "scenarios" / f"{scenario_id}.json"
        
    auto_translate.save_scenario(scenario, output_path)

def handle_spec_to_eval(args):
    """Handler for 'spec-to-eval' command."""
    from . import spec_parser
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[FAIL] Error: Markdown file not found at {input_path}")
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
    print(f"[OK] Successfully converted {input_path} to {output_path}")

def handle_import_drift(args):
    """Handler for 'import-drift' command."""
    from . import drift_importer
    input_path = Path(args.input)
    industry = args.industry
    output_dir = Path(args.output_dir) if args.output_dir else Path("industries") / industry / "scenarios"
    
    try:
        output_file = drift_importer.import_trace_as_scenario(input_path, industry, output_dir)
        print(f"[OK] Successfully imported drift from {input_path} to {output_file}")
    except Exception as e:
        print(f"[FAIL] Error importing drift: {e}")

def handle_mutate(args):
    """Handler for 'mutate' command."""
    from . import mutator
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[FAIL] Error: Input scenario not found at {input_path}")
        return
        
    with open(input_path, "r", encoding="utf-8") as f:
        scenario = json.loads(f.read())
        
    mutated = mutator.mutate_scenario(scenario, args.type)
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_{args.type}.json"
        
    mutator.save_mutated_scenario(mutated, output_path)
    print(f"[OK] Mutated scenario saved to {output_path}")

def handle_export(args):
    """Handler for 'export' command."""
    from . import exporter
    if args.format == "hf":
        exporter.HFExporter.export(args.input, args.output)

def handle_install(args):
    """Handler for 'install' command."""
    print(f"\n[Install] Fetching scenario pack: {args.pack}...")
    # Mock pack registry
    packs = {
        "telecom-pack": ["telecom"],
        "finance-pack": ["finance", "tax"],
        "security-pack": ["cybersecurity", "audit"]
    }
    
    industries = packs.get(args.pack)
    if not industries:
        print(f"❌ Error: Pack '{args.pack}' not found in registry.")
        return

    for ind in industries:
        print(f"📦 Installing {ind} scenarios...")
        # In a real app, this would download from a remote repo or S3
        # Here we just ensure the dir exists as a mock
        Path(f"industries/{ind}").mkdir(parents=True, exist_ok=True)
    
    print(f"\n✔ Pack '{args.pack}' installed successfully.")

async def handle_analyze(args):
    """Handler for 'analyze' command."""
    from . import analyzer
    print(f"\n[Analyze] Scanning repository: {args.url}...")
    try:
        scenarios = await analyzer.analyze_repo(args.url)
        print(f"✔ Found {len(scenarios)} potential agent patterns. Scenarios scaffolded in 'scenarios/auto/'.")
    except Exception as e:
        print(f"❌ Error during analysis: {e}")

def handle_ci_generate(args):
    """Handler for 'ci generate' command."""
    workflow_path = Path(".github/workflows/agent_eval.yml")
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    
    content = """name: Agent Evaluation CI

on:
  pull_request:
    branches: [ main, develop ]

jobs:
  eval:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ github.token }}
          persist-credentials: false
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install Harness
        run: pip install -e .
      - name: Run Scenarios
        run: eval-harness evaluate --path scenarios/ --attempts 3
"""
    with open(workflow_path, "w") as f:
        f.write(content)
    print(f"✔ CI workflow generated at {workflow_path}")

def handle_failures_search(args):
    """Handler for 'failures search' command."""
    print(f"\n[Failures] Searching corpus for: {args.query}...")
    # Search industries directory for scenarios containing the query
    industries_dir = Path("industries")
    matches = []
    for p in industries_dir.glob("**/*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                if args.query.lower() in f.read().lower():
                    matches.append(p)
        except:
            continue
    
    if not matches:
        print(f"No matching edge cases found for '{args.query}'.")
        return

    print(f"🔍 Found {len(matches)} relevant edge cases:")
    for m in matches[:10]:
        print(f" - {m}")
    if len(matches) > 10:
        print(f"   ... and {len(matches)-10} more.")

def handle_explain(args):
    """Handler for 'explain' command."""
    from . import explainer
    print(f"\n[Explain] Diagnosing trace: {args.path}...")
    path = Path(args.path)
    if not path.exists():
        print(f"❌ Error: File not found: {path}")
        return
        
    diagnosis = explainer.explain_trace(path)
    print("\n--- Diagnostic Report ---")
    print(f"Root Cause: {diagnosis['root_cause']}")
    print(f"Suggestion: {diagnosis['suggestion']}")
    print("-------------------------")

def handle_cleanup_runs(args):
    """Handler for 'cleanup-runs' command."""
    import time
    runs_dir = Path("runs")
    if not runs_dir.exists():
        print("[Cleanup] 'runs/' directory does not exist.")
        return

    now = time.time()
    cutoff = now - (args.days * 86400)
    
    files_to_delete = []
    for f in runs_dir.glob("*.jsonl"):
        if f.stat().st_mtime < cutoff:
            files_to_delete.append(f)

    if not files_to_delete:
        print(f"[Cleanup] No trace files older than {args.days} days found.")
        return

    print(f"[Cleanup] Found {len(files_to_delete)} files to delete:")
    for f in files_to_delete:
        print(f" - {f.name}")

    if not args.force:
        confirm = input("\nProceed with deletion? (y/N): ").strip().lower()
        if confirm != 'y':
            print("[Cleanup] Aborted.")
            return

    for f in files_to_delete:
        try:
            f.unlink()
            print(f"✔ Deleted {f.name}")
        except Exception as e:
            print(f"❌ Error deleting {f.name}: {e}")

    print("\n[Cleanup] Done.")

if __name__ == "__main__":
    main()
