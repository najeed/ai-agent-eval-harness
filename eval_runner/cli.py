"""
cli.py

Main entry point for the MultiAgentEval CLI.
Refactored to use modular handlers for better maintainability.
"""

import argparse
import os
import sys
import asyncio
from pathlib import Path
from . import __version__

# Suppress HF Hub unauthenticated request and symlink warnings
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

def get_parser(is_help=False):
    """Configures and returns the CLI parser."""
    try:
        from . import engine
        # Discovery must happen early for dynamic protocol choices
        if not is_help:
            engine.AgentAdapterRegistry._discover()
            available_protocols = list(engine.AgentAdapterRegistry._adapters.keys())
        else:
            available_protocols = ["http", "local", "socket", "autogen", "crewai", "langgraph"]
    except ImportError:
        available_protocols = ["http", "local", "socket"]

    usage_text = """
Usage: multiagent-eval <command> [options]

Core Evaluation:
  console        Launch the Visual Debugger (REST API & Frontend)
  contribute     Launch interactive wizard to create/submit scenarios
  evaluate       Run evaluation on scenarios
  playground     Interactive REPL to experiment with an agent
  quickstart     Run a 60-second demo (spawns agent + runs eval)
  record         Record interactions with an agent
  replay         Replay a run trace (Flight Recorder)
  run            Execute evaluation on a single scenario
  verify         Verify the integrity of a run trace

Specification & Scenarios:
  aes            Agent Eval Specification (AES) utilities
  catalog-search Deep search across the scenario catalog
  inspect        Show details for a specific scenario file
  lint           Verify scenario quality and AES compliance
  list           List and search available scenarios
  mutate         Generate adversarial scenario variants
  scenario       Scenario management utilities
  spec-to-eval   Convert Markdown PRD/Spec to Scenario JSON

Analysis & Reporting:
  calibrate      Measure judge agreement against human labels
  explain        Analyze trace logs to diagnose root causes
  leaderboard    Generate performance comparison from run traces
  list-metrics   List all registered evaluation metrics
  report         Generate HTML report from a run trace
  taxonomy       Show the official failure taxonomy

Utilities & Environment:
  analyze        Scan GitHub repo to auto-generate scenarios
  auto-translate Translate raw documents to JSON via local LLM
  ci             CI/CD utility commands (e.g. GitHub Actions)
  cleanup-runs   Housekeeping: Remove old trace files
  doctor         Check environment and dependencies
  export         Export run traces to external formats (e.g. HF)
  failures       Failure Corpus search utilities
  import-drift   Import production traces as scenarios
  init           Scaffold a new benchmark environment
  install        Install curated scenario packs
  plugin         Execute plugin-specific subcommands
"""
    parser = argparse.ArgumentParser(
        description="MultiAgentEval (OpenCore)",
        formatter_class=argparse.RawTextHelpFormatter,
        usage=usage_text if is_help else None
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- CORE EVALUATION ---
    console_parser = subparsers.add_parser("console", help="Launch the Visual Debugger")
    console_parser.add_argument("--host", default="127.0.0.1")
    console_parser.add_argument("--port", type=int, default=5000)
    console_parser.add_argument("--debug", action="store_true")

    subparsers.add_parser("contribute", help="Interactive wizard")

    eval_parser = subparsers.add_parser("evaluate", help="Run evaluation")
    eval_parser.add_argument("--path", required=True)
    eval_parser.add_argument("--format", default="jsonl", choices=["jsonl", "csv"])
    eval_parser.add_argument("--output", default="reports/latest_results.json")
    eval_parser.add_argument("--limit", type=int)
    eval_parser.add_argument("--attempts", type=int, default=1)
    eval_parser.add_argument("--run-log-dir")
    eval_parser.add_argument("--agent")
    eval_parser.add_argument("--protocol", default="http", choices=available_protocols)
    eval_parser.add_argument("--agent-cmd")
    eval_parser.add_argument("--agent-socket")
    eval_parser.add_argument("--agent-name")
    eval_parser.add_argument("--per-run-logs", action="store_true", default=None)
    eval_parser.add_argument("--master-log", action="store_true", default=None)
    eval_parser.add_argument("--seed", type=int)

    playground_parser = subparsers.add_parser("playground", help="Interactive REPL")
    playground_parser.add_argument("--agent")
    playground_parser.add_argument("--protocol", default="http", choices=available_protocols)
    playground_parser.add_argument("--agent-name")
    playground_parser.add_argument("--verbose", action="store_true")

    subparsers.add_parser("quickstart", help="60-second demo")

    record_parser = subparsers.add_parser("record", help="Record interactions")
    record_parser.add_argument("--agent")
    record_parser.add_argument("--protocol", default="http", choices=available_protocols)
    record_parser.add_argument("--agent-name")
    record_parser.add_argument("--verbose", action="store_true")

    replay_parser = subparsers.add_parser("replay", help="Replay run trace")
    replay_parser.add_argument("--path", default="runs/run.jsonl")

    run_parser = subparsers.add_parser("run", help="Single scenario eval")
    run_parser.add_argument("--scenario", required=True)
    run_parser.add_argument("--attempts", type=int, default=1)
    run_parser.add_argument("--agent")
    run_parser.add_argument("--protocol", default="http", choices=available_protocols)
    run_parser.add_argument("--seed", type=int)
    run_parser.add_argument("--agent-name")
    run_parser.add_argument("--verbose", action="store_true")
    run_parser.add_argument("--output")
    run_parser.add_argument("--run-log-dir")

    verify_parser = subparsers.add_parser("verify", help="Verify trace integrity")
    verify_parser.add_argument("--path", required=True)
    verify_parser.add_argument("--manifest")

    # --- SPECIFICATION & SCENARIOS ---
    aes_parser = subparsers.add_parser("aes", help="AES utilities")
    aes_sub = aes_parser.add_subparsers(dest="aes_command")
    aes_val = aes_sub.add_parser("validate")
    aes_val.add_argument("--path", required=True)

    aes_add = aes_sub.add_parser("add-standard")
    aes_add.add_argument("--id", required=True)
    aes_add.add_argument("--name", required=True)
    aes_add.add_argument("--industry", required=True)
    aes_add.add_argument("--description", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect scenario")
    inspect_parser.add_argument("--scenario-path", required=True)

    lint_parser = subparsers.add_parser("lint", help="Lint scenario")
    lint_parser.add_argument("--path", dest="target", required=True)

    list_parser = subparsers.add_parser("list", help="List scenarios")
    list_parser.add_argument("--search")
    list_parser.add_argument("--refresh", action="store_true")

    subparsers.add_parser("catalog-search", help="Search catalog").add_argument("--query", required=True)
    subparsers.add_parser("catalog-refresh", help="Refresh catalog")

    mutate_parser = subparsers.add_parser("mutate", help="Mutate scenario")
    mutate_parser.add_argument("--input", required=True)
    mutate_parser.add_argument("--type", required=True, choices=["typo", "injection", "ambiguity"])
    mutate_parser.add_argument("--output")

    scenario_parser = subparsers.add_parser("scenario", help="Scenario management")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_command")
    scenario_sub.add_parser("generate")
    scenario_ins = scenario_sub.add_parser("inspect")
    scenario_ins.add_argument("path")

    spec_parser = subparsers.add_parser("spec-to-eval", help="MD to JSON")
    spec_parser.add_argument("--input", "--path", dest="input", required=True)
    spec_parser.add_argument("--output")

    # --- ANALYSIS & REPORTING ---
    calibrate_parser = subparsers.add_parser("calibrate", help="Judge calibration")
    calibrate_parser.add_argument("--path", required=True)
    calibrate_parser.add_argument("--plot", action="store_true")

    subparsers.add_parser("explain", help="Explain trace").add_argument("--path", required=True)
    
    leaderboard_parser = subparsers.add_parser("leaderboard", help="Generate leaderboard")
    leaderboard_parser.add_argument("--dir", default="runs")
    leaderboard_parser.add_argument("--output", default="LEADERBOARD.md")

    subparsers.add_parser("list-metrics", help="List metrics")

    report_parser = subparsers.add_parser("report", help="Generate report")
    report_parser.add_argument("--path", required=True)
    report_parser.add_argument("--share", action="store_true")

    subparsers.add_parser("taxonomy", help="Show taxonomy")

    # --- UTILITIES ---
    analyze_parser = subparsers.add_parser("analyze", help="Analyze GitHub repo")
    analyze_parser.add_argument("url")

    translate_parser = subparsers.add_parser("auto-translate", help="Translate doc")
    translate_parser.add_argument("--input", required=True)
    translate_parser.add_argument("--output")
    translate_parser.add_argument("--industry")
    translate_parser.add_argument("--model", default="llama3")

    ci_parser = subparsers.add_parser("ci", help="CI utilities")
    ci_sub = ci_parser.add_subparsers(dest="ci_command")
    ci_sub.add_parser("generate")

    cleanup_parser = subparsers.add_parser("cleanup-runs", help="Cleanup traces")
    cleanup_parser.add_argument("--days", type=int, default=7)
    cleanup_parser.add_argument("--force", action="store_true")

    subparsers.add_parser("doctor", help="Check env")

    export_parser = subparsers.add_parser("export", help="Export trace")
    export_parser.add_argument("--input", required=True)
    export_parser.add_argument("--output", required=True)

    failures_parser = subparsers.add_parser("failures", help="Failure utilities")
    failures_sub = failures_parser.add_subparsers(dest="failures_command")
    failures_sub.add_parser("search").add_argument("query")

    drift_parser = subparsers.add_parser("import-drift", help="Import production traces")
    drift_parser.add_argument("--input", required=True)
    drift_parser.add_argument("--industry", required=True)

    init_parser = subparsers.add_parser("init", help="Init environment")
    init_parser.add_argument("--dir")
    init_parser.add_argument("--industry")
    init_parser.add_argument("--protocol", default="http")
    init_parser.add_argument("--standard")
    init_parser.add_argument("--registry")

    subparsers.add_parser("install", help="Install pack").add_argument("pack")

    plugin_parser = subparsers.add_parser("plugin", help="Plugin management")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command")
    plugin_sub.add_parser("list")
    plugin_reg = plugin_sub.add_parser("register")
    plugin_reg.add_argument("path")
    plugin_unreg = plugin_sub.add_parser("unregister")
    plugin_unreg.add_argument("name")

    registry_parser = subparsers.add_parser("registry", help="Registry management")
    registry_sub = registry_parser.add_subparsers(dest="registry_command")
    registry_sub.add_parser("sync")
    registry_add = registry_sub.add_parser("add")
    registry_add.add_argument("--id", required=True)
    registry_add.add_argument("--url", required=True)
    registry_sub.add_parser("search").add_argument("query")

    return parser

def reconstruct_results_from_events(events: list) -> list:
    """Helper to reconstruct results structure from JSONL events."""
    from .triage import TriageEngine
    results_map = {}
    for event in events:
        task_id = event.get("task_id", "unknown")
        ev_type = event.get("event")
        if task_id not in results_map:
            results_map[task_id] = {"task_id": task_id, "metrics": [], "conversation_history": [], "triage_tag": "SUCCESS"}
        res = results_map[task_id]
        if ev_type == "evaluation":
            res["metrics"].append({"metric": event.get("metric"), "score": event.get("value"), "threshold": event.get("threshold", 0.5), "success": event.get("success", False)})
        elif ev_type in ["prompt", "agent_response", "tool_result"]:
            role = "agent" if ev_type == "agent_response" else "user"
            content = event.get("content") or {"action": event.get("tool"), "status": event.get("status")}
            res["conversation_history"].append({"role": role, "content": content})
    final_results = list(results_map.values())
    TriageEngine.apply_triage(final_results)
    return final_results

def main():
    """Main CLI entrance."""
    is_help = "-h" in sys.argv or "--help" in sys.argv
    if "--version" in sys.argv:
        print(f"MultiAgentEval {__version__}")
        sys.exit(0)

    try:
        parser = get_parser(is_help=is_help)
        args = parser.parse_args()

        if not args.command:
            parser.print_help()
            return

        # Dynamic imports for handlers to minimize footprint
        if args.command in ["evaluate", "run", "record", "playground", "replay", "verify", "quickstart"]:
            from .handlers import evaluation as h
            if args.command == "evaluate": asyncio.run(h.handle_evaluate(args))
            elif args.command == "run": asyncio.run(h.handle_run(args))
            elif args.command == "record": asyncio.run(h.handle_record(args))
            elif args.command == "playground": asyncio.run(h.handle_playground(args))
            elif args.command == "replay": h.handle_replay(args)
            elif args.command == "verify": h.handle_verify(args)
            elif args.command == "quickstart": asyncio.run(h.handle_quickstart(args))

        elif args.command in ["aes", "inspect", "lint", "list", "catalog-search", "catalog-refresh", "mutate", "scenario", "spec-to-eval", "import-drift"]:
            from .handlers import scenarios as h
            if args.command == "aes": h.handle_aes_validate(args) if args.aes_command == "validate" else None
            elif args.command == "inspect": h.handle_inspect(args)
            elif args.command == "lint": h.handle_lint(args)
            elif args.command == "list": h.handle_list(args)
            elif args.command == "catalog-search": h.handle_catalog_search(args)
            elif args.command == "catalog-refresh": h.handle_catalog_refresh(args)
            elif args.command == "mutate": h.handle_mutate(args)
            elif args.command == "scenario":
                if args.scenario_command == "generate": h.handle_scenario_generate(args)
                elif args.scenario_command == "inspect": h.handle_inspect(args)
            elif args.command == "spec-to-eval": asyncio.run(h.handle_spec_to_eval(args))
            elif args.command == "import-drift": h.handle_import_drift(args)

        elif args.command in ["calibrate", "explain", "leaderboard", "report", "taxonomy", "list-metrics"]:
            from .handlers import analysis as h
            if args.command == "calibrate": h.handle_calibrate(args)
            elif args.command == "explain": h.handle_explain(args)
            elif args.command == "leaderboard": h.handle_leaderboard(args)
            elif args.command == "report": h.handle_report(args)
            elif args.command == "taxonomy": h.handle_taxonomy(args)
            elif args.command == "list-metrics": h.handle_list_metrics(args)

        elif args.command in ["analyze", "auto-translate", "ci", "cleanup-runs", "doctor", "export", "failures", "init", "install", "registry", "plugin"]:
            from .handlers import environment as h
            if args.command == "analyze": asyncio.run(h.handle_analyze(args))
            elif args.command == "auto-translate": asyncio.run(h.handle_auto_translate(args))
            elif args.command == "ci" and args.ci_command == "generate": h.handle_ci_generate(args)
            elif args.command == "cleanup-runs": h.handle_cleanup_runs(args)
            elif args.command == "doctor": h.handle_doctor(args)
            elif args.command == "export": h.handle_export(args)
            elif args.command == "failures" and args.failures_command == "search": h.handle_failures_search(args)
            elif args.command == "init": h.handle_init(args)
            elif args.command == "install": h.handle_install(args)
            elif args.command == "registry":
                if args.registry_command == "sync": h.handle_registry_sync(args)
                elif args.registry_command == "add": h.handle_registry_add(args)
                elif args.registry_command == "search": h.handle_registry_search(args)
            elif args.command == "plugin":
                if args.plugin_command == "list": h.handle_plugin_list(args)
                elif args.plugin_command == "register": h.handle_plugin_register(args)
                elif args.plugin_command == "unregister": h.handle_plugin_unregister(args)

        elif args.command == "console":
            from .console.app import run_server
            print(f"[CLI] Launching Visual Debugger on http://{args.host}:{args.port}")
            run_server(host=args.host, port=args.port, debug=args.debug)
        
        elif args.command == "contribute":
            from .contributor import ContributeWizard
            ContributeWizard.run()

        else:
            parser.print_help()

    except KeyboardInterrupt:
        print("\n[CLI] Interrupted.")
        sys.exit(130)
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
