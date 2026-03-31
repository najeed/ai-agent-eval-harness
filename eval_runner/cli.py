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
  console        Launch the Visual Debugger (Web UI & REST API)
  contribute     Start the interactive scenario contribution wizard
  evaluate       Execute batch evaluation on a scenario dataset
  playground     Launch an interactive REPL for agent experimentation
  quickstart     Run the 60-second engine demonstration
  record         Record live agent interactions to a session trace
  replay         Replay a previously recorded run trace
  run            Execute evaluation on a single specific scenario
  verify         Verify the cryptographic integrity of a run trace
  gate           CI/CD "Hard Gate": Enforce verification and signature checks

Specification & Scenarios:
  aes            AES Specification utilities (Validate/Register)
  catalog-search Search the global and local scenario catalogs
  inspect        Display task breakdown for a specific scenario
  lint           Static analysis for AES compliance and quality
  list           Filter and list available local scenarios
  mutate         Generate adversarial/edge-case scenario variants
  scenario       Generic scenario management (Generate/Inspect)
  spec-to-eval   Convert Markdown PRD/Specs into Scenario JSON

Analysis & Reporting:
  calibrate      Measure judge agreement against human labels
  explain        Diagnose root causes from evaluation traces
  leaderboard    Generate performance rankings from run traces
  list-metrics   List all registered evaluation metrics
  report         Generate stylized HTML reports from run traces
  taxonomy       Display the official AEH failure taxonomy

Utilities & Environment:
  analyze        Auto-generate scenarios from GitHub repositories
  auto-translate Use local LLMs to translate docs to AES JSON
  ci             GitHub Actions / CI/CD pipeline integration
  cleanup-runs   Prune old traces and rotate log artifacts
  doctor         Audit the local environment and dependencies
  export         Export traces to external formats (HF, CSV)
  failures       Search the global Failure Corpus and patterns
  import-drift   Convert production traces to evaluation scenarios
  init           Initialize a new benchmark environment
  install        Install curated industry scenario packs
  plugin         Manage external and built-in plugins
  registry       Synchronize industry scenario registries
"""
    parser = argparse.ArgumentParser(
        description="MultiAgentEval (OpenCore)",
        formatter_class=argparse.RawTextHelpFormatter,
        usage=usage_text if is_help else None
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- CORE EVALUATION ---
    console_parser = subparsers.add_parser("console", help="Launch the Visual Debugger (REST API & Frontend)")
    console_parser.add_argument("--host", default="127.0.0.1", help="Host address for the debugger server")
    console_parser.add_argument("--port", type=int, default=5000, help="Port for the debugger server")
    console_parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")

    subparsers.add_parser("contribute", help="Interactive wizard")

    eval_parser = subparsers.add_parser("evaluate", help="Run evaluation on a dataset of scenarios")
    eval_parser.add_argument("--path", required=True, help="Path to scenario JSONL/folder or URI")
    eval_parser.add_argument("--format", default="jsonl", choices=["jsonl", "csv"], help="Input dataset format")
    eval_parser.add_argument("--output", default="reports/latest_results.json", help="Path to save the evaluation results")
    eval_parser.add_argument("--limit", type=int, help="Limit the number of scenarios to process")
    eval_parser.add_argument("--attempts", type=int, default=1, help="Number of pass@k attempts per scenario")
    eval_parser.add_argument("--run-log-dir", help="Directory for storing execution traces")
    eval_parser.add_argument("--agent", help="Agent endpoint/command for execution")
    eval_parser.add_argument("--protocol", default="http", choices=available_protocols, help="Communication protocol for the agent")
    eval_parser.add_argument("--agent-cmd", help="Subprocess command (for protocol=local)")
    eval_parser.add_argument("--agent-socket", help="Socket identifier (for protocol=socket)")
    eval_parser.add_argument("--agent-name", help="Human-readable name for the evaluator agent")
    eval_parser.add_argument("--per-run-logs", action="store_true", default=None, help="Force creation of individual .jsonl traces per attempt")
    eval_parser.add_argument("--master-log", action="store_true", default=None, help="Append all results to a master run.jsonl log")
    eval_parser.add_argument("--seed", type=int, help="Random seed for deterministic evaluation")
    eval_parser.add_argument("-f", "--force", action="store_true", help="Force evaluation (bypass existing trace checks)")
    eval_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose trace logging")

    playground_parser = subparsers.add_parser("playground", help="Interactive REPL to experiment with an agent")
    playground_parser.add_argument("--agent", help="Agent endpoint or connection identifier")
    playground_parser.add_argument("--protocol", default="http", choices=available_protocols, help="Protocol for REPL interaction")
    playground_parser.add_argument("--agent-name", help="Name to display in the interactive session")
    playground_parser.add_argument("--verbose", action="store_true", help="Enable verbose debug output")

    subparsers.add_parser("quickstart", help="60-second demo")

    record_parser = subparsers.add_parser("record", help="Record interactions with an agent to a trace file")
    record_parser.add_argument("--agent", help="Target agent for recording")
    record_parser.add_argument("--protocol", default="http", choices=available_protocols, help="Recording protocol")
    record_parser.add_argument("--agent-name", help="Agent name for the trace metadata")
    record_parser.add_argument("--verbose", action="store_true", help="Log recording steps to console")

    replay_parser = subparsers.add_parser("replay", help="Replay a previously recorded run trace (Flight Recorder)")
    replay_parser.add_argument("--path", default="runs/run.jsonl", help="Path to the .jsonl trace file to replay")

    run_parser = subparsers.add_parser("run", help="Single scenario eval")
    run_parser.add_argument("--scenario", required=True)
    run_parser.add_argument("--attempts", type=int, default=1)
    run_parser.add_argument("--agent")
    run_parser.add_argument("--protocol", default="http", choices=available_protocols)
    run_parser.add_argument("--seed", type=int)
    run_parser.add_argument("--agent-name")
    run_parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose trace logging")
    run_parser.add_argument("-f", "--force", action="store_true", help="Force single scenario evaluation")
    run_parser.add_argument("--output")
    run_parser.add_argument("--run-log-dir")

    verify_parser = subparsers.add_parser("verify", help="Verify the cryptographic integrity of a run trace")
    verify_parser.add_argument("--path", required=True, help="Path to the trace file to verify")
    verify_parser.add_argument("--manifest", help="Optional path to the .manifest.json for the trace")

    gate_parser = subparsers.add_parser("gate", help="CI/CD Hard Gate: Enforce verification and signature checks")
    gate_parser.add_argument("--vc", required=True, help="Path to the Verification Certificate (manifest.json)")
    gate_parser.add_argument("--hash", help="Expected git commit hash for the verified run")
    gate_parser.add_argument("--public-key", help="Path to the ED25519 public key for signature validation")

    # --- SPECIFICATION & SCENARIOS ---
    aes_parser = subparsers.add_parser("aes", help="Agent Eval Specification (AES) utility suite")
    aes_sub = aes_parser.add_subparsers(dest="aes_command")
    aes_val = aes_sub.add_parser("validate", help="Validate a scenario file against the AES JSON schema")
    aes_val.add_argument("--path", required=True, help="Path to the scenario JSON file to validate")

    aes_add = aes_sub.add_parser("add-standard", help="Register a new industry standard to the local AES manifest")
    aes_add.add_argument("--id", required=True, help="Unique identifier for the standard (e.g., standard-v2)")
    aes_add.add_argument("--name", required=True, help="Human-readable name for the standard")
    aes_add.add_argument("--industry", required=True, help="Target industry sector (e.g., finance, healthcare)")
    aes_add.add_argument("--description", required=True, help="Detailed description of the standard's scope")

    inspect_parser = subparsers.add_parser("inspect", help="Display architectural details and task breakdown for a scenario")
    inspect_parser.add_argument("--scenario-path", required=True, help="Path to the scenario file to inspect")
    
    lint_parser = subparsers.add_parser("lint", help="Static analysis for scenario quality and AES V1.2 compliance")
    lint_parser.add_argument("--path", dest="target", required=True, help="Target scenario file or directory to lint")
    
    list_parser = subparsers.add_parser("list", help="List and filter available scenarios in the local industry registry")
    list_parser.add_argument("--search", help="Search string for scenario titles or descriptions")
    list_parser.add_argument("--refresh", action="store_true", help="Force a refresh of the local scenario cache")

    subparsers.add_parser("catalog-search", help="Deep search across the scenario catalog").add_argument("--query", required=True, help="Search query for global scenarios")
    subparsers.add_parser("catalog-refresh", help="Refresh and re-index the global scenario catalog")

    mutate_parser = subparsers.add_parser("mutate", help="Generate adversarial or edge-case variants of a base scenario")
    mutate_parser.add_argument("--input", required=True, help="Path to the base scenario file")
    mutate_parser.add_argument("--type", required=True, choices=["typo", "injection", "ambiguity"], help="Type of mutation to apply")
    mutate_parser.add_argument("-f", "--force", action="store_true", help="Force mutation (overwrite existing scenario variants)")
    mutate_parser.add_argument("--output", help="Optional path to save the mutated scenario")

    scenario_parser = subparsers.add_parser("scenario", help="Scenario management")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_command")
    scenario_sub.add_parser("generate")
    scenario_ins = scenario_sub.add_parser("inspect")
    scenario_ins.add_argument("path")

    spec_parser = subparsers.add_parser("spec-to-eval", help="MD to JSON")
    spec_parser.add_argument("--input", "--path", dest="input", required=True)
    spec_parser.add_argument("--output")

    # --- ANALYSIS & REPORTING ---
    calibrate_parser = subparsers.add_parser("calibrate", help="Measure and visualize judge agreement against human-labeled ground truth")
    calibrate_parser.add_argument("--path", required=True, help="Path to the calibrated run trace or results file")
    calibrate_parser.add_argument("--plot", action="store_true", help="Generate a visualization of the calibration results")

    subparsers.add_parser("explain", help="Explain trace").add_argument("--path", required=True)
    
    leaderboard_parser = subparsers.add_parser("leaderboard", help="Generate a performance comparison leaderboard from multiple run traces")
    leaderboard_parser.add_argument("--dir", default="runs", help="Directory containing run traces to aggregate")
    leaderboard_parser.add_argument("--output", default="LEADERBOARD.md", help="Output path for the generated leaderboard")

    subparsers.add_parser("list-metrics", help="Display descriptions for all registered evaluation metrics")

    report_parser = subparsers.add_parser("report", help="Generate a stylized HTML report from a specific evaluation run")
    report_parser.add_argument("--path", required=True, help="Path to the results or trace file")
    report_parser.add_argument("--share", action="store_true", help="Generate a shareable report link (if configured)")

    subparsers.add_parser("taxonomy", help="Show the official AEH failure taxonomy for categorization")

    # --- UTILITIES ---
    analyze_parser = subparsers.add_parser("analyze", help="Scan a GitHub repository to auto-generate evaluation scenarios")
    analyze_parser.add_argument("url", help="URL of the GitHub repository to analyze")
 
    translate_parser = subparsers.add_parser("auto-translate", help="Translate raw technical documents to AES JSON via local LLM")
    translate_parser.add_argument("--input", required=True, help="Path to the raw document (PDF, MD, TXT)")
    translate_parser.add_argument("--output", help="Optional path for the translated JSON output")
    translate_parser.add_argument("--industry", help="Target industry sector for context-aware translation")
    translate_parser.add_argument("--model", default="llama3", help="Local model identifier for the translation task")

    ci_parser = subparsers.add_parser("ci", help="CI/CD utility suite for automated pipeline integration")
    ci_sub = ci_parser.add_subparsers(dest="ci_command")
    ci_sub.add_parser("generate", help="Generate a GitHub Actions workflow for the current environment")

    cleanup_parser = subparsers.add_parser("cleanup-runs", help="Housekeeping: Remove old run traces and log artifacts")
    cleanup_parser.add_argument("--days", type=int, default=7, help="Remove files older than N days")
    cleanup_parser.add_argument("--force", action="store_true", help="Bypass confirmation prompt for deletion")

    subparsers.add_parser("doctor", help="Audit the local environment for configuration markers and dependencies")

    export_parser = subparsers.add_parser("export", help="Export run traces to external formats (e.g., HuggingFace datasets)")
    export_parser.add_argument("--input", required=True, help="Path to the local trace file")
    export_parser.add_argument("--output", required=True, help="Target path/identifier for the exported data")

    failures_parser = subparsers.add_parser("failures", help="Failure Corpus search and analysis utilities")
    failures_sub = failures_parser.add_subparsers(dest="failures_command")
    failures_sub.add_parser("search", help="Search for similar failures across the global corpus").add_argument("query", help="Search query string")

    drift_parser = subparsers.add_parser("import-drift", help="Import production traces as new evaluation scenarios")
    drift_parser.add_argument("--input", required=True, help="Path to production log or trace")
    drift_parser.add_argument("--industry", required=True, help="Assume sector-specific schema for the import")

    init_parser = subparsers.add_parser("init", help="Scaffold a new benchmark environment and local industry registry")
    init_parser.add_argument("--dir", help="Target directory for initialization")
    init_parser.add_argument("--industry", help="Primary industry sector to initialize")
    init_parser.add_argument("--protocol", default="http", help="Default agent communication protocol")
    init_parser.add_argument("--standard", help="Initial AES standard to adopt")
    init_parser.add_argument("--registry", help="Remote registry URL for scenario synchronization")

    subparsers.add_parser("install", help="Install curated scenario packs for specific industrial benchmarks").add_argument("pack", help="Name of the scenario pack to install")

    plugin_parser = subparsers.add_parser("plugin", help="Execute and manage plugin-specific subcommands")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command")
    plugin_sub.add_parser("list", help="List all registered and active plugins")
    plugin_reg = plugin_sub.add_parser("register", help="Register a new external plugin by path")
    plugin_reg.add_argument("path", help="File system path to the plugin directory")
    plugin_unreg = plugin_sub.add_parser("unregister", help="Unregister an existing plugin by name")
    plugin_unreg.add_argument("name", help="Identifier of the plugin to remove")

    registry_parser = subparsers.add_parser("registry", help="Industry scenario registry management")
    registry_sub = registry_parser.add_subparsers(dest="registry_command")
    registry_sub.add_parser("sync", help="Synchronize the local registry with remote industry standards")
    registry_add = registry_sub.add_parser("add", help="Add a new scenario manifest to the local registry")
    registry_add.add_argument("--id", required=True, help="Unique ID for the registry entry")
    registry_add.add_argument("--url", required=True, help="Source URL or path for the manifest")
    registry_sub.add_parser("search", help="Search the local and remote registries").add_argument("query", help="Search string")

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
        if args.command in ["evaluate", "run", "record", "playground", "replay", "verify", "gate", "quickstart"]:
            from .handlers import evaluation as h
            if args.command == "evaluate": asyncio.run(h.handle_evaluate(args))
            elif args.command == "run": asyncio.run(h.handle_run(args))
            elif args.command == "record": asyncio.run(h.handle_record(args))
            elif args.command == "playground": asyncio.run(h.handle_playground(args))
            elif args.command == "replay": h.handle_replay(args)
            elif args.command == "verify": h.handle_verify(args)
            elif args.command == "gate": h.handle_gate(args)
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
