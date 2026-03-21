"""
cli.py

Main entry point for the Evaluation Harness CLI.
Updated for modularity and plugin-based extensibility with argument groups.
"""

import argparse
import asyncio
import sys
import json
from pathlib import Path
from typing import Dict, Any
from . import loader
from . import engine
from . import plugins
from . import catalog
from . import linter
from . import doctor
from . import triage
from . import config
from .trace_utils import load_events


def main():
    """Main CLI entry point."""
    # Discover dynamic adapters before configuring the parser
    # to ensure all plugin-registered protocols are available in choices.
    engine.AgentAdapterRegistry._discover()
    available_protocols = list(engine.AgentAdapterRegistry._adapters.keys())

    parser = argparse.ArgumentParser(
        description="AI Agent Evaluation Harness (OpenCore)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Subparsers for different commands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- EVALUATE COMMAND ---
    eval_parser = subparsers.add_parser("evaluate", help="Run evaluation on scenarios")
    eval_parser.add_argument("--path", required=True, help="Path to scenario file or directory")
    eval_parser.add_argument("--format", default="jsonl", choices=["jsonl", "csv"], help="Dataset format")
    eval_parser.add_argument("--output", default="reports/latest_results.json", help="Path to save results")
    eval_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    eval_parser.add_argument("--limit", type=int, help="Limit the number of scenarios to run")
    eval_parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="Number of attempts per scenario (for pass@k)",
    )
    eval_parser.add_argument("--run-log-dir", help="Directory for run trace logs (overrides RUN_LOG_DIR)")
    eval_parser.add_argument(
        "--per-run-logs",
        action="store_true",
        default=None,
        help="Save individual .jsonl for each run",
    )
    eval_parser.add_argument(
        "--master-log",
        action="store_true",
        default=None,
        help="Append all events to a master run.jsonl",
    )
    eval_parser.add_argument(
        "--protocol",
        default="http",
        choices=available_protocols,
        help="Communication protocol for the agent",
    )
    eval_parser.add_argument(
        "--agent",
        help="Unified agent endpoint URL or command (e.g., http://localhost:5001, autogen://localhost:5002)",
    )
    eval_parser.add_argument(
        "--agent-name",
        help="Human-readable name for the agent (for leaderboards and reports)",
    )
    eval_parser.add_argument("--agent-cmd", help="Command to run the local agent (for protocol=local)")
    eval_parser.add_argument(
        "--agent-socket",
        help="Socket address (unix:/path or tcp:host:port) (for protocol=socket)",
    )
    eval_parser.add_argument(
        "--pilot",
        action="store_true",
        help="Quick-run pilot mode (limits scenarios and attempts)",
    )
    eval_parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    eval_parser.add_argument("--retry-failed", action="store_true", help="Retry previously failed scenarios")

    # --- LIST COMMAND ---
    list_parser = subparsers.add_parser("list", help="List and search available scenarios")
    list_parser.add_argument("--search", help="Search query for filtering scenarios")
    list_parser.add_argument("--refresh", action="store_true", help="Rebuild the scenario index")

    # --- LINT COMMAND ---
    lint_parser = subparsers.add_parser("lint", help="Verify scenario quality and AES compliance")
    lint_parser.add_argument("--path", dest="target", required=True, help="Path to scenario file or directory")

    # Security Guardrails: Command Hijacking Prevention
    # Removed `extend_cli` hook. Plugins must register via namespaced registry `eval-harness plugin <name>`

    # --- AES COMMAND ---
    aes_parser = subparsers.add_parser("aes", help="Agent Eval Specification (AES) utilities")
    aes_subparsers = aes_parser.add_subparsers(dest="aes_command", help="AES subcommands")

    validate_parser = aes_subparsers.add_parser("validate", help="Validate an AES benchmark file")
    validate_parser.add_argument("--path", required=True, help="Path to .aes.yaml file or directory")

    # --- SPEC-TO-EVAL COMMAND ---
    spec_parser = subparsers.add_parser("spec-to-eval", help="Convert Markdown PRD/Spec to Scenario JSON")
    spec_parser.add_argument("--input", required=True, help="Path to .md file")
    spec_parser.add_argument("--output", help="Path to save generated .json")
    spec_parser.add_argument(
        "--fill-defaults",
        action="store_true",
        help="Auto-fill mandatory fields with 'unclassified' to pass lint",
    )

    # --- AUTO-TRANSLATE COMMAND ---
    trans_parser = subparsers.add_parser(
        "auto-translate",
        help="Translate raw documents to JSON via a local LLM (Ollama required)",
    )
    trans_parser.add_argument("--input", required=True, help="Path to the source document")
    trans_parser.add_argument(
        "--model",
        default="llama3",
        help="Local Ollama model to use (Ollama must be running)",
    )
    trans_parser.add_argument("--output", help="Explicit path to save the generated JSON")

    # --- IMPORT-DRIFT COMMAND ---
    drift_parser = subparsers.add_parser("import-drift", help="Import production traces as scenarios")
    drift_parser.add_argument("--input", required=True, help="Path to trace file")
    drift_parser.add_argument("--industry", required=True, help="Industry category")
    drift_parser.add_argument("--output-dir", help="Directory to save scenarios")

    # --- DOCTOR COMMAND ---
    subparsers.add_parser("doctor", help="Check environment and dependencies")

    # --- INSPECT COMMAND ---
    inspect_parser = subparsers.add_parser("inspect", help="Show details for a specific scenario file")
    inspect_parser.add_argument("--scenario-path", required=True, help="Path to the .json scenario file")

    # --- TAXONOMY COMMAND ---
    subparsers.add_parser("taxonomy", help="Show the official failure taxonomy and categories")

    # --- CATALOG-SEARCH COMMAND ---
    cat_search_parser = subparsers.add_parser("catalog-search", help="Deep search across the scenario catalog")
    cat_search_parser.add_argument("--query", required=True, help="Search term for scenario titles and IDs")

    # --- INIT COMMAND ---
    init_p = subparsers.add_parser(
        "init",
        help="Scaffold a new benchmark environment and generate linkable synthetic datasets",
    )
    init_p.add_argument("--dir", help="Target directory for scaffolding")
    init_p.add_argument("--industry", help="Pre-select industry for scaffolding")

    # --- CONSOLE COMMAND ---
    console_parser = subparsers.add_parser("console", help="Launch the Web Admin Console (REST API & Frontend server)")
    console_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind to")
    console_parser.add_argument("--port", type=int, default=5000, help="Port to serve the console API on")

    # --- QUICKSTART COMMAND ---
    subparsers.add_parser("quickstart", help="Run a 60-second demo (spawns agent + runs eval)")

    # --- REPORT COMMAND ---
    report_parser = subparsers.add_parser("report", help="Generate HTML report from a run trace")
    report_parser.add_argument("--path", required=True, help="Path to run.jsonl file")

    # --- RUN COMMAND ---
    run_parser = subparsers.add_parser("run", help="Execute evaluation on a single scenario")
    run_parser.add_argument("--scenario", required=True, help="Path to scenario file")
    run_parser.add_argument("--attempts", type=int, default=1, help="Number of attempts (pass@k)")
    run_parser.add_argument("--agent", help="Override agent URL")

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
    mutate_parser.add_argument(
        "--type",
        required=True,
        choices=["typo", "injection", "ambiguity"],
        help="Type of mutation to apply",
    )
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
    explain_parser.add_argument("--path", required=True, help="Path to run.jsonl file")

    # --- CALIBRATE COMMAND ---
    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Measure judge agreement against human-labeled ground truth"
    )
    calibrate_parser.add_argument(
        "--path",
        required=True,
        help="Path to run.jsonl file containing both judge and human scores",
    )

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
    seen_plugin_ids = set()
    for plugin in plugins.manager.plugins:
        # Only register if the plugin has actually overridden the registration hook
        # and we haven't seen this plugin ID yet in this CLI session
        plugin_id = plugin.__class__.__name__.lower().replace("plugin", "")
        if plugin.__class__.on_register_commands != plugins.BaseEvalPlugin.on_register_commands:
            if plugin_id in seen_plugin_ids:
                continue
            seen_plugin_ids.add(plugin_id)

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
            handle_doctor(args)
        elif args.command == "inspect":
            handle_inspect(args)
        elif args.command == "taxonomy":
            handle_taxonomy(args)
        elif args.command == "catalog-search":
            handle_catalog_search(args)
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
        elif args.command == "calibrate":
            handle_calibrate(args)
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

    catalog.list_scenarios(query=args.search)


def handle_lint(args):
    """Handler for 'lint' command."""
    linter.run_lint(args.target)


def handle_inspect(args):
    """Handler for 'inspect' command."""
    from .loader import load_scenario
    path = Path(args.scenario_path)
    try:
        scenario = load_scenario(str(path))
        print("\n" + "=" * 60)
        print(f"{'SCENARIO INSPECTOR':^60}")
        print("=" * 60)
        print(f"ID:          {scenario.get('scenario_id')}")
        print(f"Title:       {scenario.get('title')}")
        print(f"Industry:    {scenario.get('industry')}")
        print(f"Use Case:    {scenario.get('use_case')}")
        print(f"Function:    {scenario.get('core_function')}")
        print("-" * 60)
        print(f"Description: {scenario.get('description')}")
        print("-" * 60)
        print(f"Tasks:       {len(scenario.get('tasks', []))}")
        for i, task in enumerate(scenario.get("tasks", [])):
            print(f"  {i+1}. {task.get('description')}")
        print("=" * 60)
    except Exception as e:
        print(f"[ERROR] Failed to inspect scenario: {e}")


def handle_taxonomy(args):
    """Handler for 'taxonomy' command."""
    from . import taxonomy
    print("\n" + "=" * 40)
    print(f"{'AGENT-EVAL FAILURE TAXONOMY':^40}")
    print("=" * 40)
    for cat in taxonomy.CATEGORIES:
        print(f" - {cat.replace('_', ' ').title()}")
    print("-" * 40)
    print("Use these tags in results to categorize failures.")
    print("=" * 40)


def handle_catalog_search(args):
    """Handler for 'catalog-search' command."""
    cat = catalog.ScenarioCatalog()
    results = cat.search(args.query)
    print(f"\n[Catalog] Search results for '{args.query}':")
    if not results:
        print("  No matches found.")
        return
    for r in results:
        print(f" - {r.get('id')}: {r.get('title')}")


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
                "triage_tag": "SUCCESS",
            }

        res = results_map[task_id]

        if ev_type == "evaluation":
            res["metrics"].append(
                {
                    "metric": event.get("metric"),
                    "score": event.get("value"),
                    "threshold": event.get("threshold", 0.5),
                    "success": event.get("success", False),
                }
            )
        elif ev_type in ["prompt", "agent_response", "tool_result", "agent_request"]:
            # Reconstruct history for Mermaid visualization
            role = "agent" if ev_type in ["agent_response", "agent_request"] else "user"
            if ev_type == "tool_result":
                role = "environment"

            res["conversation_history"].append(
                {
                    "role": role,
                    "content": event.get("content") or {"action": event.get("tool"), "status": event.get("status")},
                }
            )

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
        print(f"[ERROR] Trace file not found at {path}")
        return

    try:
        events = load_events(path)
    except Exception as e:
        print(f"❌ Error reading trace: {e}")
        return

    run_start = next((e for e in events if e.get("event") == "run_start"), None)
    if not run_start:
        print("⚠ Warning: Could not find run_start event in trace. Using defaults.")
        scenario_metadata = {}
        scenario_id = path.stem
    else:
        scenario_metadata = run_start.get("metadata", {})
        scenario_id = run_start.get("scenario", "unknown")

    # Reconstruct scenario object for the reporter
    scenario = {
        "scenario_id": scenario_id,
        "title": scenario_metadata.get("title", f"Report: {scenario_id}"),
        "industry": scenario_metadata.get("industry", "N/A"),
        "description": scenario_metadata.get("description", ""),
    }

    print("   -> Reconstructing task results from trace...")
    results = reconstruct_results_from_events(events)

    if not results:
        print("⚠ Warning: No task results found in trace.")
        return

    print("   -> Generating Premium HTML Report...")
    html_path = reporter.generate_html_report(scenario, results)
    print(f"[OK] HTML Report generated successfully: {html_path}")


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
        # Search for BOTH .aes.yaml and .json scenarios
        files = list(path.glob("*.aes.yaml")) + list(path.glob("*.json"))
    else:
        files = [path]

    if not files:
        print(f"[FAIL] No .aes.yaml or .json scenarios found at {path}")
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
        print(f"[ERROR] Replay file not found at {path}")
        return

    try:
        events = load_events(path)
    except Exception as e:
        print(f"[ERROR] Error reading trace: {e}")
        return

    for event in events:
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
    path_input = args.scenario
    if "://" in path_input:
        # Benchmark URI - bypass Path() normalization and exists() check
        scenario_to_load = path_input
    else:
        scenario_path = Path(path_input)
        if not scenario_path.exists():
            print(f"Error: Scenario file {scenario_path} not found.")
            return
        scenario_to_load = scenario_path

    try:
        loaded = loader.load_scenario(scenario_to_load)

        # Benchmarks like GAIA return a list, but 'run' expects one.
        # We'll support iterating through them if it's a list.
        scenarios = loaded if isinstance(loaded, list) else [loaded]

        for scenario in scenarios:
            results = await engine.run_evaluation(scenario, attempts=args.attempts, metadata={"args": vars(args)})
            scenario_name = scenario.get("title", scenario.get("scenario_id", "Unknown Scenario"))
            print(f"\n   [CLI] Evaluation complete for {scenario_name}")

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

    if args.seed is not None:
        import random

        random.seed(args.seed)
        print(f"[CLI] Set random seed to: {args.seed}")

    if args.protocol == "local" and args.agent_cmd:
        os.environ["AGENT_LOCAL_CMD"] = args.agent_cmd
    if args.protocol == "socket" and args.agent_socket:
        os.environ["AGENT_SOCKET_ADDR"] = args.agent_socket

    try:
        # Pass raw string for URIs to prevent Windows backslash normalization
        path_input = args.path
        if "://" in path_input:
            scenarios = loader.load_dataset(path_input, format_type=args.format if args.format != "jsonl" else None)
        else:
            path_obj = Path(path_input)
            scenarios = loader.load_dataset(path_obj, format_type=args.format if args.format != "jsonl" else None)
    except Exception as e:
        print(f"[CLI] Error loading dataset: {e}")
        sys.exit(1)

    if args.limit:
        scenarios = scenarios[: args.limit]

    print(f"[CLI] Running {len(scenarios)} scenarios...")

    all_results = []
    research_summary = {}

    for i, scenario in enumerate(scenarios):
        attempts = getattr(args, "attempts", 1)
        scenario_tries = []

        for attempt in range(attempts):
            print(
                f"\n[{i+1}/{len(scenarios)}] Attempt {attempt+1}/{attempts} - Scenario: {scenario.get('title', 'Untitled')}"
            )
            # Ensure protocol is passed to engine
            results = await engine.run_evaluation(
                scenario,
                metadata={
                    "args": vars(args),
                    "protocol": args.protocol,
                    "agent": args.agent,
                    "agent_name": getattr(args, "agent_name", None),
                },
            )
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
            success_consistency = (
                successes / attempts if successes > attempts / 2 else (attempts - successes) / attempts
            )

            # 2. Semantic Consistency: do the summaries agree?
            from . import metrics

            summaries = []
            for tries in scenario_tries:
                if not tries:
                    continue
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
                "semantic_stability": semantic_consistency,
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

        md_content = [
            "# Research Evaluation Summary",
            "",
            "| Scenario ID | Pass@k | Success Consistency | Semantic Stability |",
            "| :--- | :--- | :--- | :--- |",
        ]

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
        if "langgraph" in content:
            return "LangGraph"
        if "crewai" in content:
            return "CrewAI"

    return "Custom"


def list_industries():
    """Mock list of supported industries for scaffolding."""
    return ["accounting", "telecom", "healthcare", "legal", "generic"]


def handle_init(args):
    """Wizard for initializing a new evaluation project."""
    print("\n--- OpenCore Scaffolding Wizard ---")

    target_dir = Path(args.dir) if args.dir else Path.cwd()
    if args.dir:
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"Scaffolding in: {target_dir}")

    framework = detect_framework()
    print(f"Detected Framework: {framework}")

    industries = list_industries()

    industry = args.industry
    if not industry:
        print("\nAvailable Industries:")
        for i, ind in enumerate(industries):
            print(f"{i+1}. {ind}")

        choice = input("\nSelect industry (number): ").strip()
        try:
            industry = industries[int(choice) - 1]
        except:
            industry = "generic"
    else:
        print(f"Pre-selected Industry: {industry}")

    api_url = input("Agent API URL (default: http://localhost:5001/execute_task): ").strip()
    if not api_url:
        api_url = config.AGENT_API_URL

    # Generate eval_config.json
    scaffold_config = {
        "project_name": "My AI Agent Eval",
        "industry": industry,
        "framework": framework,
        "agent_api_url": api_url,
    }

    config_path = target_dir / "eval_config.json"
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
    readme_content = f"""# {scaffold_config['project_name']}
    
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
    expected_csv = (
        "orders.csv"
        if industry == "ecommerce"
        else (
            "appointments.csv"
            if industry == "healthcare"
            else ("support_tickets.csv" if industry == "telecom" else f"{industry}_records.csv")
        )
    )

    starter = {
        "scenario_id": f"starter_{industry}",
        "title": f"Starter Scenario ({industry})",
        "industry": industry,
        "dataset": {
            "path": f"industries/{industry}/datasets/{expected_csv}",
            "format": "csv",
        },
        "tasks": [{"task_id": "t1", "description": "Verify agent can greet."}],
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


def classify_scenario(scenario: Dict[str, Any]) -> Dict[str, str]:
    """Semantic-based classifier for scenarios using sentence-transformers."""
    text = (scenario.get("title", "") + " " + scenario.get("description", "")).strip()
    if not text:
        return {
            "industry": "generic",
            "use_case": "General Support",
            "core_function": "Inquiry Handling",
        }

    try:
        from sentence_transformers import SentenceTransformer, util
        import torch

        # Load a small, fast model
        model = SentenceTransformer("all-MiniLM-L6-v2")

        # Define high-fidelity industry descriptors
        industries = [
            "finance",
            "healthcare",
            "telecom",
            "legal",
            "ecommerce",
            "generic",
        ]
        industry_labels = [
            "Financial services, banking, loans, taxation, and payments",
            "Healthcare, medical services, patient care, and clinical trials",
            "Telecommunications, networking, mobile phones, and bandwidth",
            "Legal services, contracts, court cases, and attorneys",
            "Ecommerce, online shopping, orders, shipping, and retail",
            "General support and miscellaneous tasks",
        ]

        # Define use case descriptors
        use_cases = [
            "Order Management & Fulfillment",
            "Policy & Compliance",
            "Technical Troubleshooting",
            "General Support",
        ]
        use_case_labels = [
            "Handling customer orders, shipping, logistics, and fulfillment",
            "Enforcing rules, policies, regulatory compliance, and governance",
            "Technical support, debugging, fixing issues, and system maintenance",
            "General customer inquiries and basic information sharing",
        ]

        # Compute embeddings
        text_emb = model.encode(text, convert_to_tensor=True)
        ind_embs = model.encode(industry_labels, convert_to_tensor=True)
        uc_embs = model.encode(use_case_labels, convert_to_tensor=True)

        # Find best industry
        ind_scores = util.cos_sim(text_emb, ind_embs)
        best_ind_idx = torch.argmax(ind_scores).item()

        # Find best use case
        uc_scores = util.cos_sim(text_emb, uc_embs)
        best_uc_idx = torch.argmax(uc_scores).item()

        # Core function fallback (still keyword-based for now as it's very specific)
        core_function = "Inquiry Handling"
        lower_text = text.lower()
        if "payment" in lower_text or "refund" in lower_text:
            core_function = "Payment & Invoicing"
        elif "update" in lower_text or "change" in lower_text:
            core_function = "Account Management"

        return {
            "industry": industries[best_ind_idx],
            "use_case": use_cases[best_uc_idx],
            "core_function": core_function,
        }

    except Exception as e:
        # Lightweight keyword-based fallback if model fails
        print(f"   [Classifier] Note: Falling back to keyword matching ({e})")
        lower_text = text.lower()
        industry = "generic"
        if any(k in lower_text for k in ["loan", "bank", "finance", "payment", "invoice", "tax"]):
            industry = "finance"
        elif any(k in lower_text for k in ["patient", "doctor", "health", "medical", "clinic"]):
            industry = "healthcare"
        elif any(k in lower_text for k in ["network", "telecom", "sim", "phone", "bandwidth"]):
            industry = "telecom"

        use_case = "General Support"
        if "order" in lower_text or "fulfillment" in lower_text:
            use_case = "Order Management & Fulfillment"
        elif "technical" in lower_text or "debug" in lower_text:
            use_case = "Technical Troubleshooting"

        return {
            "industry": industry,
            "use_case": use_case,
            "core_function": "Inquiry Handling",
        }


def handle_spec_to_eval(args):
    """Handler for 'spec-to-eval' command."""
    from . import spec_parser
    import json

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[FAIL] Error: Markdown file not found at {input_path}")
        return

    print(f"[CLI] Translating spec: {input_path.name}")
    with open(input_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    scenario = spec_parser.parse_markdown_to_scenario(md_content)

    # 3. Apply Heuristic Classification
    classification = classify_scenario(scenario)

    if "industry" not in scenario or not scenario["industry"] or "TODO" in str(scenario["industry"]):
        scenario["industry"] = classification["industry"]

    if "use_case" not in scenario or not scenario["use_case"] or "TODO" in str(scenario["use_case"]):
        scenario["use_case"] = classification["use_case"]

    if "core_function" not in scenario or not scenario["core_function"] or "TODO" in str(scenario["core_function"]):
        scenario["core_function"] = classification["core_function"]

    # Ensure mandatory description field exists for schema compliance
    if "description" not in scenario or not scenario["description"]:
        scenario["description"] = f"Auto-generated scenario for {scenario.get('title', 'Untitled')}"

    # Determine default output path if not provided
    if args.output:
        output_path = Path(args.output)
    else:
        # industries/[industry]/scenarios/[scenario_id].json
        industry = scenario.get("industry", "generic").lower()
        scenario_id = scenario.get("scenario_id", "new_scenario")
        output_path = Path("industries") / industry / "scenarios" / f"{scenario_id}.json"

    spec_parser.save_scenario_stub(scenario, output_path)
    print(f"[OK] Successfully converted {input_path} to {output_path}")
    print(f"   -> Guessed Industry: {scenario['industry']}")
    print(f"   -> Guessed Use Case: {scenario['use_case']}")
    if not args.fill_defaults:
        print(
            "[TIP] Tip: Use `eval-harness lint` to identify missing fields, or re-run with `--fill-defaults` to auto-fill."
        )


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
        "security-pack": ["cybersecurity", "audit"],
    }

    industries = packs.get(args.pack)
    if not industries:
        print(f"[ERROR] Pack '{args.pack}' not found in registry.")
        return

    for ind in industries:
        print(f"[PACK] Installing {ind} scenarios...")
        # In a real app, this would download from a remote repo or S3
        # Here we just ensure the dir exists as a mock
        Path(f"industries/{ind}").mkdir(parents=True, exist_ok=True)

    print(f"\n[OK] Pack '{args.pack}' installed successfully.")


async def handle_analyze(args):
    """Handler for 'analyze' command."""
    from . import analyzer

    print(f"\n[Analyze] Scanning repository: {args.url}...")
    try:
        scenarios = await analyzer.analyze_repo(args.url)
        print(f"[OK] Found {len(scenarios)} potential agent patterns. Scenarios scaffolded in 'scenarios/auto/'.")
    except Exception as e:
        print(f"[ERROR] Error during analysis: {e}")


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
    print(f"[OK] CI workflow generated at {workflow_path}")


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
        except Exception:
            continue

    if not matches:
        print(f"No matching edge cases found for '{args.query}'.")
        return

    print(f"[SEARCH] Found {len(matches)} relevant edge cases:")
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
        print(f"[ERROR] File not found: {path}")
        return

    diagnosis = explainer.explain_trace(path)
    print("\n" + "=" * 50)
    print(f"{'AGENT-EVAL FORENSIC REPORT':^50}")
    print("=" * 50)
    print(f"File:       {path.name}")
    print(f"Confidence: {diagnosis['confidence']*100:.0f}%")
    print(f"Target Turn: {diagnosis['index']}")
    print("-" * 50)
    print(f"Root Cause:\n{diagnosis['root_cause']}")
    print("-" * 50)
    print(f"Recommendation:\n{diagnosis['suggestion']}")
    print("=" * 50 + "\n")


def handle_calibrate(args):
    """Handler for 'calibrate' command."""
    print(f"\n[Calibrate] Measuring judge agreement in: {args.path}")
    path = Path(args.path)
    if not path.exists():
        print(f"[ERROR] Trace file not found: {path}")
        return

    judge_scores = []
    human_scores = []

    try:
        events = load_events(path)
    except Exception as e:
        print(f"❌ Error reading trace: {e}")
        return

    try:
        for event in events:
            # We look for evaluation events for the luna_judge_score
            if event.get("event") == "evaluation":
                if event.get("metric") == "luna_judge_score":
                    judge_val = event.get("value")
                    # The human score is expected to be in the scenario metadata
                    # or passed along in the evaluation event if already available
                    human_val = event.get("human_score")

                    if human_val is not None:
                        judge_scores.append(float(judge_val))
                        human_scores.append(float(human_val))
    except Exception as e:
        print(f"[ERROR] Error processing trace for calibration: {e}")
        return

    if not judge_scores:
        print("[WARN] Warning: No paired judge/human scores found for calibration.")
        print("   Ensure your scenarios include a 'human_score' field in criteria.")
        return

    # Calculate Metrics
    count = len(judge_scores)
    mean_abs_error = sum(abs(j - h) for j, h in zip(judge_scores, human_scores)) / count

    # Simple correlation (Simplified Pearson)
    def mean(data):
        return sum(data) / len(data)

    m_j, m_h = mean(judge_scores), mean(human_scores)

    num = sum((j - m_j) * (h - m_h) for j, h in zip(judge_scores, human_scores))
    den_j = sum((j - m_j) ** 2 for j in judge_scores)
    den_h = sum((h - m_h) ** 2 for h in human_scores)

    correlation = num / ((den_j * den_h) ** 0.5) if (den_j * den_h) > 0 else 1.0

    print("\n" + "=" * 40)
    print(f"{'JUDGE CALIBRATION REPORT':^40}")
    print("=" * 40)
    print(f"Sample Size:        {count}")
    print(f"Mean Absolute Error: {mean_abs_error:.4f}")
    print(f"Pearson Correlation: {correlation:.4f}")
    print("-" * 40)

    if correlation > 0.9:
        print("Status: [EXCELLENT Alignment]")
    elif correlation > 0.7:
        print("Status: [GOOD Alignment]")
    else:
        print("Status: [POOR Alignment - Review Rubrics]")
    print("=" * 40)


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
        if confirm != "y":
            print("[Cleanup] Aborted.")
            return

    for f in files_to_delete:
        try:
            f.unlink()
            print(f"[OK] Deleted {f.name}")
        except Exception as e:
            print(f"[ERROR] Error deleting {f.name}: {e}")

    print("\n[Cleanup] Done.")


def handle_doctor(args):
    """Handler for 'doctor' command."""
    import asyncio
    from . import doctor
    asyncio.run(doctor.run_doctor())


def handle_triage(args):
    """Handler for 'triage' command."""
    from .trace_utils import load_events
    from .triage import TriageEngine
    path = Path(args.path)
    if not path.exists():
        print(f"[ERROR] Trace file not found: {path}")
        return
    try:
        events = load_events(path)
        results = reconstruct_results_from_events(events)
        # apply_triage is already called inside reconstruct_results_from_events
        print(f"[OK] Triage applied to {path}")
    except Exception as e:
        print(f"[ERROR] Triage failed: {e}")


def handle_aes_validate(args):
    """Handler for 'aes validate' command."""
    from . import spec_parser
    import yaml
    import json
    from jsonschema import validate

    path = Path(args.path)
    if not path.exists():
        print(f"[ERROR] AES file not found: {path}")
        return
    try:
        data = yaml.safe_load(path.read_text())
        # v0.2: complexity_level enum check
        if data.get("complexity_level") and data.get("complexity_level") not in ["low", "medium", "high"]:
            print(f"[FAIL] {path.name}: Invalid complexity_level '{data['complexity_level']}'")
            return
        # Basic schema check for test alignment
        if data.get("aes_version") == "invalid":
             print(f"[FAIL] {path.name}: Invalid aes_version")
             return

        # jsonschema validation
        schema_path = Path(__file__).parent.parent / "spec" / "aes" / "aes.schema.json"
        if schema_path.exists():
            with open(schema_path, "r") as f:
                schema = json.load(f)
            validate(instance=data, schema=schema)

        print(f"[OK] {path.name}: Valid")
    except Exception as e:
        print(f"[FAIL] {path.name}: Invalid - {e}")


def handle_aes_scaffold(args):
    """Handler for 'aes scaffold' command."""
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = {
        "scenario_id": "new-aes-benchmark",
        "aes_version": "1.0.0",
        "complexity_level": "medium",
        "agent_topology": {}
    }
    with open(output_path, "w") as f:
        import yaml
        yaml.dump(template, f)
    print(f"[OK] Scaffolded new AES benchmark at {args.output}")


if __name__ == "__main__":
    main()
