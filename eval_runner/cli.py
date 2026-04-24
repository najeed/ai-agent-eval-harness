"""
cli.py

Main entry point for the AgentV CLI.
Refactored to use a Unified Functional Dispatcher and dynamic Extension Discovery.
"""

import argparse
import inspect
import os
import sys
from pathlib import Path

from . import __version__
from .utils import safe_run_async

# Industrial Encoding Bridge
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

_parser_cache = None
_parser_argv_hash = None


def _invalidate_parser_cache():
    """Industrial Cache Invalidation. Clears the parser singleton."""
    global _parser_cache, _parser_argv_hash
    _parser_cache = None
    _parser_argv_hash = None


# --- LAZY DISPATCHERS (Zero-Touch Infrastructure) ---


def _dispatch_console(args):
    from .console.app import run_server

    print(f"[CLI] Launching Visual Debugger on http://{args.host}:{args.port}")
    run_server(host=args.host, port=args.port, debug=args.debug)
    return 0


def _dispatch_contribute(args):
    from .contributor import ContributeWizard

    ContributeWizard.run()
    return 0


def _dispatch_evaluation(args):
    from .handlers import evaluation as h

    method_name = f"handle_{args.command.replace('-', '_')}"
    handler = getattr(h, method_name)
    return handler(args)


def _dispatch_scenarios(args):
    from .handlers import scenarios as h

    if args.command == "aes":
        return h.handle_aes_validate(args) if args.aes_command == "validate" else 0
    if args.command == "scenario":
        if args.scenario_command == "inspect":
            return h.handle_inspect(args)
        method_name = f"handle_scenario_{args.scenario_command}"
        return getattr(h, method_name)(args)

    method_name = f"handle_{args.command.replace('-', '_')}"
    # Industrial Normalization: catalog-search
    if args.command == "catalog-search" and not getattr(args, "query", None):
        args.query = getattr(args, "query_flag", None)

    handler = getattr(h, method_name)
    return handler(args)


def _dispatch_analysis(args):
    from .handlers import analysis as h

    method_name = f"handle_{args.command.replace('-', '_')}"
    handler = getattr(h, method_name)
    return handler(args)


def _dispatch_environment(args):
    from .handlers import environment as h

    if args.command == "ci":
        return h.handle_ci_generate(args) if args.ci_command == "generate" else 0
    if args.command == "failures":
        return h.handle_failures_search(args) if args.failures_command == "search" else 0
    if args.command == "registry":
        method_name = f"handle_registry_{args.registry_command}"
        return getattr(h, method_name)(args)
    if args.command == "plugin":
        method_name = f"handle_plugin_{args.plugin_command}"
        return getattr(h, method_name)(args)
    if args.command == "list-plugins":
        return h.handle_plugin_list(args)

    method_name = f"handle_{args.command.replace('-', '_')}"
    # Industrial Normalization: analyze
    if args.command == "analyze" and not getattr(args, "url", None):
        args.url = getattr(args, "repo_url", None)

    handler = getattr(h, method_name)
    return handler(args)


def get_parser(is_help: bool = False):
    """Configures and returns the CLI parser."""
    global _parser_cache, _parser_argv_hash

    current_hash = hash(tuple(sys.argv))
    if _parser_cache is not None and _parser_argv_hash == current_hash:
        return _parser_cache

    try:
        from . import engine

        needs_discovery = False
        if len(sys.argv) > 1:
            cmd = sys.argv[1]
            needs_discovery = cmd in {
                "evaluate",
                "run",
                "playground",
                "record",
                "quickstart",
                "init",
                "console",
                "doctor",
            }

        if not is_help and needs_discovery:
            engine.AgentAdapterRegistry._discover()
            available_protocols = list(engine.AgentAdapterRegistry._adapters.keys())
        else:
            available_protocols = ["http", "local", "socket", "autogen", "crewai", "langgraph"]
    except ImportError:
        available_protocols = ["http", "local", "socket"]

    usage_text = """
Usage: agentv <command> [options]

1. Authoring & Scaffolding
  init           Scaffold a new benchmark environment
  scenario       Generic scenario management (Generate/Inspect)
  spec-to-eval   Convert Markdown PRD/Specs into Scenario JSON
  mutate         Generate adversarial/edge-case scenario variants
  analyze        Auto-generate scenarios from GitHub repositories
  auto-translate Use local LLMs to translate docs to AES JSON
  install        Install industrial scenario packs (e.g., Fintech, Healthcare)

2. Discovery & Exploration
  list           Filter and list available local scenarios
  catalog-search Search the global and local scenario catalogs
  catalog-refresh Synchronize the local catalog with upstream registries
  inspect        Display task breakdown for a specific scenario
  list-metrics   List all registered evaluation metrics
  taxonomy       Display the official AEH failure taxonomy
  list-plugins   Display all active and registered plugins

3. Executing Evaluations
  run            Execute evaluation on a single specific scenario
  evaluate       Execute batch evaluation on a scenario dataset
  quickstart     Run the 60-second engine demonstration

4. Debugging & Diagnosis
  replay         Replay a previously recorded run trace
  explain        Diagnose root causes from evaluation traces
  failures       Search the global Failure Corpus and patterns
  playground     Launch an interactive REPL for agent experimentation
  record         Record live agent interactions to a session trace

5. Reporting & Benchmarking
  report         Generate stylized HTML reports from run traces
  leaderboard    Generate performance rankings from run traces
  calibrate      Measure judge agreement against human labels

6. Trust & Verification
  verify         Verify the cryptographic integrity of a run trace
  certify        Generate a Verification Certificate (VC) for a trace
  gate           CI/CD "Hard Gate": Enforce verification/compliance
  aes            AES Specification utilities (Validate/Register)
  lint           Static analysis for AES compliance and quality

7. Automation & Integration
  ci             GitHub Actions / CI/CD pipeline integration
  export         Export traces to external formats (HF, CSV)
  import-drift   Convert production traces to evaluation scenarios
  registry       Synchronize industry scenario registries

8. Maintenance & Control
  console        Launch the Visual Debugger (Web UI & REST API)
  contribute     Start the interactive contribution wizard
  cleanup-runs   Prune old traces and rotate log artifacts
  doctor         Audit the environment and dependencies
  plugin         Manage external and built-in plugins
"""
    parser = argparse.ArgumentParser(
        description="AgentV (OpenCore)",
        formatter_class=argparse.RawTextHelpFormatter,
        usage=usage_text if is_help else None,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Industrial Discovery: Load external command extensions via Entry Points
    import importlib.metadata

    try:
        eps = importlib.metadata.entry_points(group="agentv.extensions")
    except TypeError:
        eps = importlib.metadata.entry_points().get("agentv.extensions", [])

    for ep in eps:
        try:
            register_func = ep.load()
            register_func(subparsers)
        except Exception as e:
            sys.stderr.write(f"   [CLI] Warning: Failed to load extension {ep.name}: {e}\n")

    # --- CORE COMMANDS ---

    # 1. MAINTENANCE & CONTROL
    console_parser = subparsers.add_parser("console", help="Launch the Visual Debugger")
    console_parser.add_argument("--host", default="127.0.0.1")
    console_parser.add_argument("--port", type=int, default=5000)
    console_parser.add_argument("--debug", action="store_true")
    console_parser.set_defaults(func=_dispatch_console)

    contribute_parser = subparsers.add_parser("contribute", help="Interactive wizard")
    contribute_parser.set_defaults(func=_dispatch_contribute)

    doctor_parser = subparsers.add_parser("doctor", help="Audit environment")
    doctor_parser.set_defaults(func=_dispatch_environment)
    doctor_parser.add_argument("--registry", action="store_true")

    cleanup_parser = subparsers.add_parser("cleanup-runs", help="Prune traces")
    cleanup_parser.set_defaults(func=_dispatch_environment)
    cleanup_parser.add_argument("--days", type=int, default=7)
    cleanup_parser.add_argument("--force", action="store_true")

    # 2. EVALUATION
    eval_parser = subparsers.add_parser("evaluate", help="Batch evaluation")
    eval_parser.set_defaults(func=_dispatch_evaluation)
    eval_parser.add_argument("--path", required=True)
    eval_parser.add_argument("--format", default="jsonl")
    eval_parser.add_argument("--output", default="reports/latest_results.json")
    eval_parser.add_argument("--run-id")
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
    eval_parser.add_argument("-f", "--force", action="store_true")
    eval_parser.add_argument("-v", "--verbose", action="store_true")
    eval_parser.add_argument("--plugin", "--plugins", action="append")

    run_parser = subparsers.add_parser("run", help="Single scenario eval")
    run_parser.set_defaults(func=_dispatch_evaluation)
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--path", "--scenario", dest="scenario", required=True)
    run_parser.add_argument("--attempts", type=int, default=1)
    run_parser.add_argument("--agent")
    run_parser.add_argument("--protocol", default="http", choices=available_protocols)
    run_parser.add_argument("--seed", type=int)
    run_parser.add_argument("--agent-name")
    run_parser.add_argument("-v", "--verbose", action="store_true")
    run_parser.add_argument("-f", "--force", action="store_true")
    run_parser.add_argument("--output")
    run_parser.add_argument("--run-log-dir")
    run_parser.add_argument("--plugin", "--plugins", action="append")

    playground_parser = subparsers.add_parser("playground", help="Interactive REPL")
    playground_parser.set_defaults(func=_dispatch_evaluation)
    playground_parser.add_argument("--path", "--agent", dest="agent")
    playground_parser.add_argument("--protocol", default="http", choices=available_protocols)
    playground_parser.add_argument("--agent-name")
    playground_parser.add_argument("--verbose", action="store_true")

    quickstart_parser = subparsers.add_parser("quickstart", help="60-second demo")
    quickstart_parser.set_defaults(func=_dispatch_evaluation)

    # 3. DISCOVERY & EXPLORATION
    list_parser = subparsers.add_parser("list", help="List scenarios")
    list_parser.set_defaults(func=_dispatch_scenarios)
    list_parser.add_argument("--search")
    list_parser.add_argument("--refresh", action="store_true")

    catalog_search_parser = subparsers.add_parser("catalog-search", help="Search catalogs")
    catalog_search_parser.set_defaults(func=_dispatch_scenarios)
    catalog_search_parser.add_argument("query", nargs="?", help="Search query (positional)")
    catalog_search_parser.add_argument("--query", dest="query_flag", help="Search query (flagged)")
    subparsers.add_parser("list-metrics", help="List metrics").set_defaults(func=_dispatch_analysis)
    subparsers.add_parser("taxonomy", help="Show failure taxonomy").set_defaults(
        func=_dispatch_analysis
    )
    subparsers.add_parser("list-plugins", help="List active plugins").set_defaults(
        func=_dispatch_environment
    )

    # 4. DEBUGGING & DIAGNOSIS
    record_parser = subparsers.add_parser("record", help="Record interactions")
    record_parser.set_defaults(func=_dispatch_evaluation)
    record_parser.add_argument("--path", "--scenario", "--agent", dest="agent")
    record_parser.add_argument("--protocol", default="http", choices=available_protocols)
    record_parser.add_argument("--agent-name")
    record_parser.add_argument("--verbose", action="store_true")

    replay_parser = subparsers.add_parser("replay", help="Replay a trace")
    replay_parser.set_defaults(func=_dispatch_evaluation)
    replay_parser.add_argument("--run-id", required=True, help="[SSOT] Mandatory identifier")

    explain_parser = subparsers.add_parser("explain", help="Diagnose root causes")
    explain_parser.set_defaults(func=_dispatch_analysis)
    explain_parser.add_argument("--run-id", required=True)

    failures_parser = subparsers.add_parser("failures", help="Failure utilities")
    failures_sub = failures_parser.add_subparsers(dest="failures_command")
    failures_search = failures_sub.add_parser("search")
    failures_search.add_argument("query")
    failures_search.set_defaults(func=_dispatch_environment)

    # 4. TRUST & VERIFICATION
    verify_parser = subparsers.add_parser("verify", help="Verify trace integrity")
    verify_parser.set_defaults(func=_dispatch_evaluation)
    verify_parser.add_argument(
        "--path", "--run-id", dest="run_id", required=True, help="[SSOT] Mandatory Run ID"
    )

    certify_parser = subparsers.add_parser("certify", help="Generate VC")
    certify_parser.set_defaults(func=_dispatch_evaluation)
    certify_parser.add_argument(
        "--path", "--run-id", dest="run_id", required=True, help="[SSOT] Mandatory Run ID"
    )
    certify_parser.add_argument("--identity", "-i", default="system_id")
    certify_parser.add_argument("--status", default="pass", choices=["pass", "fail", "warning"])
    certify_parser.add_argument("--score", type=float, default=1.0)
    certify_parser.add_argument("--policy-ref")
    certify_parser.add_argument("--ttl", type=int)
    certify_parser.add_argument("--fingerprint")

    gate_parser = subparsers.add_parser("gate", help="CI/CD Gate")
    gate_parser.set_defaults(func=_dispatch_evaluation)
    gate_parser.add_argument(
        "--path", "--run-id", dest="run_id", required=True, help="[SSOT] Mandatory Run ID"
    )
    gate_parser.add_argument("--hash")
    gate_parser.add_argument("--verify-ledger", action="store_true")

    aes_parser = subparsers.add_parser("aes", help="AES tools")
    aes_sub = aes_parser.add_subparsers(dest="aes_command")
    aes_val = aes_sub.add_parser("validate")
    aes_val.set_defaults(func=_dispatch_scenarios)
    aes_val.add_argument("--path", required=True)
    aes_val.add_argument("--export")

    aes_add = aes_sub.add_parser("add-standard")
    aes_add.set_defaults(func=_dispatch_scenarios)
    aes_add.add_argument("--id", required=True)
    aes_add.add_argument("--name", required=True)
    aes_add.add_argument("--industry", required=True)
    aes_add.add_argument("--description", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect scenario")
    inspect_parser.set_defaults(func=_dispatch_scenarios)
    inspect_parser.add_argument("--path", "--scenario-path", dest="path", required=True)

    lint_parser = subparsers.add_parser("lint", help="Lint scenario")
    lint_parser.set_defaults(func=_dispatch_scenarios)
    lint_parser.add_argument("--path", dest="target", required=True)

    scenario_parser = subparsers.add_parser("scenario", help="Scenario management")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_command")
    scenario_gen = scenario_sub.add_parser("generate")
    scenario_gen.set_defaults(func=_dispatch_scenarios)
    scenario_ins = scenario_sub.add_parser("inspect")
    scenario_ins.add_argument("--path", required=True)
    scenario_ins.set_defaults(func=_dispatch_scenarios)

    spec_parser = subparsers.add_parser("spec-to-eval", help="MD to JSON")
    spec_parser.set_defaults(func=_dispatch_scenarios)
    spec_parser.add_argument("--input", "--path", "--markdown", dest="input", required=True)
    spec_parser.add_argument("--output")

    mutate_parser = subparsers.add_parser("mutate", help="Generate variants")
    mutate_parser.set_defaults(func=_dispatch_scenarios)
    mutate_parser.add_argument("--path", "--input", dest="input", required=True)
    mutate_parser.add_argument("--type", choices=["typo", "injection", "ambiguity"], required=True)
    mutate_parser.add_argument("-f", "--force", action="store_true")
    mutate_parser.add_argument("--output")

    catalog_refresh_parser = subparsers.add_parser("catalog-refresh", help="Refresh catalog")
    catalog_refresh_parser.set_defaults(func=_dispatch_scenarios)

    drift_parser = subparsers.add_parser("import-drift", help="Import production traces")
    drift_parser.set_defaults(func=_dispatch_scenarios)
    drift_parser.add_argument("--path", "--input", dest="input", required=True)
    drift_parser.add_argument("--industry", required=True)

    # 6. REPORTING & ANALYSIS
    report_parser = subparsers.add_parser("report", help="Generate HTML report")
    report_parser.set_defaults(func=_dispatch_analysis)
    report_parser.add_argument("--run-id", required=True)
    report_parser.add_argument("--share", action="store_true")

    leaderboard_parser = subparsers.add_parser("leaderboard", help="Generate leaderboard")
    leaderboard_parser.set_defaults(func=_dispatch_analysis)
    leaderboard_parser.add_argument("--dir", default="runs")
    leaderboard_parser.add_argument("--output", default="LEADERBOARD.md")

    calibrate_parser = subparsers.add_parser("calibrate", help="Measure judge agreement")
    calibrate_parser.set_defaults(func=_dispatch_analysis)
    calibrate_parser.add_argument("--run-id", required=True)
    calibrate_parser.add_argument("--golden")
    calibrate_parser.add_argument("--plot", action="store_true")

    # 7. UTILITIES & ENVIRONMENT
    init_parser = subparsers.add_parser("init", help="Initialize workspace")
    init_parser.set_defaults(func=_dispatch_environment)
    init_parser.add_argument("--dir")
    init_parser.add_argument("--industry")
    init_parser.add_argument("--protocol", default="http")
    init_parser.add_argument("--standard")
    init_parser.add_argument("--registry")

    install_parser = subparsers.add_parser("install", help="Install templates")
    install_parser.set_defaults(func=_dispatch_environment)
    install_parser.add_argument("pack")

    analyze_parser = subparsers.add_parser("analyze", help="Analyze repository")
    analyze_parser.set_defaults(func=_dispatch_environment)
    analyze_parser.add_argument("repo_url", nargs="?", help="Repository URL to analyze")
    analyze_parser.add_argument("--path", "--url", dest="url", help="Local path or URL (flagged)")

    translate_parser = subparsers.add_parser("auto-translate", help="Auto-translate docs")
    translate_parser.set_defaults(func=_dispatch_environment)
    translate_parser.add_argument("--path", "--input", dest="input", required=True)
    translate_parser.add_argument("--output")
    translate_parser.add_argument("--industry")
    translate_parser.add_argument("--model", default="llama3")

    ci_parser = subparsers.add_parser("ci", help="CI/CD utilities")
    ci_sub = ci_parser.add_subparsers(dest="ci_command")
    ci_gen = ci_sub.add_parser("generate")
    ci_gen.set_defaults(func=_dispatch_environment)

    registry_parser = subparsers.add_parser("registry", help="Registry management")
    registry_sub = registry_parser.add_subparsers(dest="registry_command")
    registry_sync = registry_sub.add_parser("sync")
    registry_sync.set_defaults(func=_dispatch_environment)
    registry_add = registry_sub.add_parser("add")
    registry_add.set_defaults(func=_dispatch_environment)
    registry_add.add_argument("--id", required=True)
    registry_add.add_argument("url")

    registry_search = registry_sub.add_parser("search")
    registry_search.add_argument("query")
    registry_search.set_defaults(func=_dispatch_environment)

    export_parser = subparsers.add_parser("export", help="Export traces")
    export_parser.set_defaults(func=_dispatch_environment)
    export_parser.add_argument("--input", "--run-id", dest="input", required=True)
    export_parser.add_argument("--output", required=True)

    plugin_parser = subparsers.add_parser("plugin", help="Plugin management")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command")
    plugin_list_sub = plugin_sub.add_parser("list")
    plugin_list_sub.set_defaults(func=_dispatch_environment)
    plugin_reg = plugin_sub.add_parser("register")
    plugin_reg.set_defaults(func=_dispatch_environment)
    plugin_reg.add_argument("path")

    plugin_unreg = plugin_sub.add_parser("unregister")
    plugin_unreg.set_defaults(func=_dispatch_environment)
    plugin_unreg.add_argument("name")

    _parser_cache = parser
    _parser_argv_hash = current_hash
    return parser


def main():
    """Main CLI entrance."""
    is_help = "-h" in sys.argv or "--help" in sys.argv
    if "--version" in sys.argv:
        print(f"AgentV {__version__}")
        sys.exit(0)

    try:
        parser = get_parser(is_help=is_help)
        args = parser.parse_args()

        # [Audit BUG-04] Early initialization of run-log-dir to prevent FileNotFoundError
        run_log_dir = getattr(args, "run_log_dir", None)
        if run_log_dir and isinstance(run_log_dir, str):
            os.environ["RUN_LOG_DIR"] = run_log_dir
            Path(run_log_dir).mkdir(parents=True, exist_ok=True)

        # Unified Functional Dispatcher
        if hasattr(args, "func") and args.func:
            res = args.func(args)
            if inspect.iscoroutine(res):
                sys.exit(safe_run_async(res) or 0)
            else:
                sys.exit(res or 0)

        if not args.command:
            parser.print_help()
            return

        parser.print_help()

    except KeyboardInterrupt:
        print("\n[CLI] Interrupted.")
        sys.exit(130)
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        from . import plugins

        plugins.manager.finalize()


if __name__ == "__main__":
    main()
