"""
cli.py

Main entry point for the AgentV CLI.
Refactored to use modular handlers for better maintainability.
"""

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .utils import safe_run_async

# Industrial Encoding Bridge (v1.2.3)
# Forces UTF-8 for stdout/stderr to support high-fidelity Unicode symbols across Win/Linux/Unix.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Suppress HF Hub unauthenticated request and symlink warnings
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


# Parser cache for performance
_parser_cache = None
_parser_argv_hash = None


def _invalidate_parser_cache():
    """Invalidate the parser cache, e.g., when sys.argv changes."""
    global _parser_cache, _parser_argv_hash
    _parser_cache = None
    _parser_argv_hash = None


def get_parser(is_help=False):
    """Configures and returns the CLI parser."""
    global _parser_cache, _parser_argv_hash

    # Check if we can use cached parser
    current_hash = hash(tuple(sys.argv))
    if _parser_cache is not None and _parser_argv_hash == current_hash:
        return _parser_cache

    try:
        from . import engine

        # Discovery is heavy: trigger only for commands that need agent protocols
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
            # Minimal core set for non-interactive commands or help
            available_protocols = ["http", "local", "socket", "autogen", "crewai", "langgraph"]
    except ImportError:
        available_protocols = ["http", "local", "socket"]
    usage_text = """
Usage: agentv <command> [options]

1. Authoring & Scaffolding (Intent: Create new tests)
  init           Scaffold a new benchmark environment
  scenario       Generic scenario management (Generate/Inspect)
  spec-to-eval   Convert Markdown PRD/Specs into Scenario JSON
  mutate         Generate adversarial/edge-case scenario variants
  analyze        Auto-generate scenarios from GitHub repositories
  auto-translate Use local LLMs to translate docs to AES JSON

2. Discovery & Exploration (Intent: Find scenarios/info)
  list           Filter and list available local scenarios
  catalog-search Search the global and local scenario catalogs
  inspect        Display task breakdown for a specific scenario
  list-metrics   List all registered evaluation metrics
  taxonomy       Display the official AEH failure taxonomy
  list-plugins   Display all active and registered plugins

3. Executing Evaluations (Intent: Run tests)
  run            Execute evaluation on a single specific scenario
  evaluate       Execute batch evaluation on a scenario dataset
  quickstart     Run the 60-second engine demonstration

4. Debugging & Diagnosis (Intent: Fix tests)
  replay         Replay a previously recorded run trace
  explain        Diagnose root causes from evaluation traces
  failures       Search the global Failure Corpus and patterns
  playground     Launch an interactive REPL for agent experimentation
  record         Record live agent interactions to a session trace

5. Reporting & Benchmarking (Intent: Analyze performance)
  report         Generate stylized HTML reports from run traces
  leaderboard    Generate performance rankings from run traces
  calibrate      Measure judge agreement against human labels

6. Trust & Verification (Intent: Prove validity)
  verify         Verify the cryptographic integrity of a run trace
  certify        Generate a Verification Certificate (VC) for a trace
  gate           CI/CD "Hard Gate": Enforce verification/compliance
  aes            AES Specification utilities (Validate/Register)
  lint           Static analysis for AES compliance and quality

7. Automation & Integration (Intent: Scale & Integrate)
  ci             GitHub Actions / CI/CD pipeline integration
  export         Export traces to external formats (HF, CSV)
  import-drift   Convert production traces to evaluation scenarios
  registry       Synchronize industry scenario registries

8. Maintenance & Control (Intent: Govern environment)
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

    # --- CORE EVALUATION ---
    console_parser = subparsers.add_parser(
        "console", help="Launch the Visual Debugger (REST API & Frontend)"
    )
    console_parser.add_argument(
        "--host", default="127.0.0.1", help="Host address for the debugger server"
    )
    console_parser.add_argument(
        "--port", type=int, default=5000, help="Port for the debugger server"
    )
    console_parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")

    subparsers.add_parser("contribute", help="Interactive wizard")

    eval_parser = subparsers.add_parser("evaluate", help="Run evaluation on a dataset of scenarios")
    eval_parser.add_argument(
        "--path",
        required=True,
        help=(
            "Cataloged scenario ID (e.g., 'loan_risk') OR project-relative path "
            "to a scenario JSON/dataset. (Check 'agentv list' for IDs)"
        ),
    )
    eval_parser.add_argument(
        "--format", default="jsonl", choices=["jsonl", "csv"], help="Dataset format"
    )
    eval_parser.add_argument(
        "--output",
        default="reports/latest_results.json",
        help="Path to save the aggregate session report (JSONL/CSV).",
    )
    eval_parser.add_argument("--run-id", help="Authoritative Run ID for this evaluation bench.")
    eval_parser.add_argument("--limit", type=int, help="Limit the number of scenarios to run.")
    eval_parser.add_argument(
        "--attempts", type=int, default=1, help="Number of pass@k attempts per scenario"
    )
    eval_parser.add_argument("--run-log-dir", help="Directory for storing execution traces")
    eval_parser.add_argument("--agent", help="Agent endpoint URL or command")
    eval_parser.add_argument(
        "--protocol",
        default="http",
        choices=available_protocols,
        help="Communication protocol for the agent",
    )
    eval_parser.add_argument("--agent-cmd", help="Subprocess command (for protocol=local)")
    eval_parser.add_argument("--agent-socket", help="Socket identifier (for protocol=socket)")
    eval_parser.add_argument("--agent-name", help="Human-readable name for the evaluator agent")
    eval_parser.add_argument(
        "--per-run-logs",
        action="store_true",
        default=None,
        help="Force creation of individual .jsonl traces per attempt",
    )
    eval_parser.add_argument(
        "--master-log",
        action="store_true",
        default=None,
        help="Append all results to a master run.jsonl log",
    )
    eval_parser.add_argument("--seed", type=int, help="Random seed for deterministic evaluation")
    eval_parser.add_argument(
        "-f", "--force", action="store_true", help="Force evaluation (bypass existing trace checks)"
    )
    eval_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose trace logging"
    )
    eval_parser.add_argument(
        "--plugin", "--plugins", action="append", help="Load external plugins (paths or modules)"
    )

    playground_parser = subparsers.add_parser(
        "playground", help="Interactive REPL to experiment with an agent"
    )
    playground_parser.add_argument("--agent", help="Agent endpoint or connection identifier")
    playground_parser.add_argument(
        "--protocol",
        default="http",
        choices=available_protocols,
        help="Protocol for REPL interaction",
    )
    playground_parser.add_argument(
        "--agent-name", help="Name to display in the interactive session"
    )
    playground_parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose debug output"
    )

    subparsers.add_parser("quickstart", help="60-second demo")

    record_parser = subparsers.add_parser(
        "record", help="Record interactions with an agent to a trace file"
    )
    record_parser.add_argument("--agent", help="Target agent for recording")
    record_parser.add_argument(
        "--protocol", default="http", choices=available_protocols, help="Recording protocol"
    )
    record_parser.add_argument("--agent-name", help="Agent name for the trace metadata")
    record_parser.add_argument(
        "--verbose", action="store_true", help="Log recording steps to console"
    )

    replay_parser = subparsers.add_parser(
        "replay", help="Replay a previously recorded run trace (Flight Recorder)"
    )
    replay_parser.add_argument(
        "--run-id", required=True, help="[SSOT] Mandatory identifier for the evaluation run"
    )

    run_parser = subparsers.add_parser("run", help="Single scenario eval")
    run_parser.add_argument("--run-id", help="Authoritative Run ID for this run.")
    run_parser.add_argument(
        "--scenario",
        required=True,
        help="Cataloged scenario ID OR project-relative path to the scenario JSON file.",
    )
    run_parser.add_argument("--attempts", type=int, default=1)
    run_parser.add_argument("--agent")
    run_parser.add_argument("--protocol", default="http", choices=available_protocols)
    run_parser.add_argument("--seed", type=int)
    run_parser.add_argument("--agent-name")
    run_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose trace logging"
    )
    run_parser.add_argument(
        "-f", "--force", action="store_true", help="Force single scenario evaluation"
    )
    run_parser.add_argument("--output")
    run_parser.add_argument("--run-log-dir")
    run_parser.add_argument(
        "--plugin", "--plugins", action="append", help="Load external plugins (paths or modules)"
    )

    verify_parser = subparsers.add_parser(
        "verify", help="Verify the cryptographic integrity of a run trace"
    )
    verify_parser.add_argument(
        "--run-id", required=True, help="[SSOT] Mandatory Run ID for autonomous artifact discovery"
    )
    certify_parser = subparsers.add_parser(
        "certify", help="Generate a Verification Certificate (VC) for a trace run"
    )
    certify_parser.add_argument(
        "--run-id", required=True, help="[SSOT] Mandatory Run ID for autonomous artifact discovery"
    )
    certify_parser.add_argument(
        "--identity", "-i", default="system_id", help="Identity ID for signing (default: system_id)"
    )
    certify_parser.add_argument(
        "--status",
        default="pass",
        choices=["pass", "fail", "warning"],
        help="Compliance status to embed",
    )
    certify_parser.add_argument(
        "--score", type=float, default=1.0, help="Compliance score (0.0-1.0) to embed"
    )
    certify_parser.add_argument(
        "--policy-ref", help="Reference to the policy being certified against"
    )
    certify_parser.add_argument("--ttl", type=int, help="Governance TTL in days (overrides config)")
    certify_parser.add_argument(
        "--fingerprint",
        help="Optional hardware/environment fingerprint ID to embed in the certificate",
    )

    gate_parser = subparsers.add_parser(
        "gate", help="Industrial CI/CD Gatekeeper: Verify certificates and integrity"
    )
    gate_parser.add_argument(
        "--run-id", required=True, help="[SSOT] Mandatory Run ID for autonomous artifact discovery"
    )
    gate_parser.add_argument(
        "--hash", help="Optional commit hash to verify against manifest metadata"
    )
    gate_parser.add_argument(
        "--verify-ledger",
        action="store_true",
        help="Perform full forensic hash check of all sidecar artifacts",
    )

    # --- SPECIFICATION & SCENARIOS ---
    aes_parser = subparsers.add_parser("aes", help="Agent Eval Specification (AES) utility suite")
    aes_sub = aes_parser.add_subparsers(dest="aes_command")
    aes_val = aes_sub.add_parser(
        "validate", help="Validate a scenario file against the AES JSON schema"
    )
    aes_val.add_argument("--path", required=True, help="Path to the scenario JSON file to validate")
    aes_val.add_argument("--export", help="Path to save the validated AES.YAML variant")

    aes_add = aes_sub.add_parser(
        "add-standard", help="Register a new industry standard to the local AES manifest"
    )
    aes_add.add_argument(
        "--id", required=True, help="Unique identifier for the standard (e.g., standard-v2)"
    )
    aes_add.add_argument("--name", required=True, help="Human-readable name for the standard")
    aes_add.add_argument(
        "--industry", required=True, help="Target industry sector (e.g., finance, healthcare)"
    )
    aes_add.add_argument(
        "--description", required=True, help="Detailed description of the standard's scope"
    )

    inspect_parser = subparsers.add_parser(
        "inspect", help="Display architectural details and task breakdown for a scenario"
    )
    inspect_parser.add_argument(
        "--scenario-path",
        required=True,
        help="Cataloged scenario ID OR project-relative path to inspect.",
    )

    lint_parser = subparsers.add_parser(
        "lint", help="Static analysis for scenario quality and AES V1.2 compliance"
    )
    lint_parser.add_argument(
        "--path", dest="target", required=True, help="Target scenario file or directory to lint"
    )

    list_parser = subparsers.add_parser(
        "list", help="List and filter available scenarios in the local industry registry"
    )
    list_parser.add_argument("--search", help="Search string for scenario titles or descriptions")
    list_parser.add_argument(
        "--refresh", action="store_true", help="Force a refresh of the local scenario cache"
    )

    subparsers.add_parser(
        "catalog-search", help="Deep search across the scenario catalog"
    ).add_argument("--query", required=True, help="Search query for global scenarios")
    subparsers.add_parser(
        "catalog-refresh", help="Refresh and re-index the global scenario catalog"
    )

    mutate_parser = subparsers.add_parser(
        "mutate", help="Generate adversarial or edge-case variants of a base scenario"
    )
    mutate_parser.add_argument("--input", required=True, help="Path to the base scenario file")
    mutate_parser.add_argument(
        "--type",
        required=True,
        choices=["typo", "injection", "ambiguity"],
        help="Type of mutation to apply",
    )
    mutate_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force mutation (overwrite existing scenario variants)",
    )
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
    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Measure and visualize judge agreement against human-labeled ground truth"
    )
    calibrate_parser.add_argument(
        "--run-id", required=True, help="[SSOT] Mandatory Run ID for autonomous artifact discovery"
    )
    calibrate_parser.add_argument(
        "--golden", help="Optional path to a golden manifest (JSON) for ground truth"
    )
    calibrate_parser.add_argument(
        "--plot", action="store_true", help="Generate a visualization of the calibration results"
    )

    explain_parser = subparsers.add_parser(
        "explain", help="Diagnose root causes from evaluation traces"
    )
    explain_parser.add_argument(
        "--run-id", required=True, help="[SSOT] Mandatory Run ID for autonomous artifact discovery"
    )

    leaderboard_parser = subparsers.add_parser(
        "leaderboard", help="Generate a performance comparison leaderboard from multiple run traces"
    )
    leaderboard_parser.add_argument(
        "--dir", default="runs", help="Directory containing run traces to aggregate"
    )
    leaderboard_parser.add_argument(
        "--output", default="LEADERBOARD.md", help="Output path for the generated leaderboard"
    )

    subparsers.add_parser(
        "list-metrics", help="Display descriptions for all registered evaluation metrics"
    )
    subparsers.add_parser(
        "list-plugins", help="Display all active and persistently registered plugins"
    )

    report_parser = subparsers.add_parser(
        "report", help="Generate a stylized HTML report from a specific evaluation run"
    )
    report_parser.add_argument(
        "--run-id", required=True, help="[SSOT] Mandatory Run ID for autonomous artifact discovery"
    )
    report_parser.add_argument(
        "--share", action="store_true", help="Generate a shareable report link (if configured)"
    )

    subparsers.add_parser(
        "taxonomy", help="Show the official AEH failure taxonomy for categorization"
    )

    # --- UTILITIES ---
    analyze_parser = subparsers.add_parser(
        "analyze", help="Scan a GitHub repository to auto-generate evaluation scenarios"
    )
    analyze_parser.add_argument("url", help="URL of the GitHub repository to analyze")

    translate_parser = subparsers.add_parser(
        "auto-translate", help="Translate raw technical documents to AES JSON via local LLM"
    )
    translate_parser.add_argument(
        "--input", required=True, help="Path to the raw document (PDF, MD, TXT)"
    )
    translate_parser.add_argument("--output", help="Optional path for the translated JSON output")
    translate_parser.add_argument(
        "--industry", help="Target industry sector for context-aware translation"
    )
    translate_parser.add_argument(
        "--model", default="llama3", help="Local model identifier for the translation task"
    )

    ci_parser = subparsers.add_parser(
        "ci", help="CI/CD utility suite for automated pipeline integration"
    )
    ci_sub = ci_parser.add_subparsers(dest="ci_command")
    ci_sub.add_parser(
        "generate", help="Generate a GitHub Actions workflow for the current environment"
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup-runs", help="Housekeeping: Remove old run traces and log artifacts"
    )
    cleanup_parser.add_argument(
        "--days", type=int, default=7, help="Remove files older than N days"
    )
    cleanup_parser.add_argument(
        "--force", action="store_true", help="Bypass confirmation prompt for deletion"
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Audit the local environment for configuration markers and dependencies"
    )
    doctor_parser.add_argument(
        "--registry", action="store_true", help="Display the detailed shim resource registry report"
    )

    export_parser = subparsers.add_parser(
        "export", help="Export run traces to external formats (e.g., HuggingFace datasets)"
    )
    export_parser.add_argument("--input", required=True, help="Path to the local trace file")
    export_parser.add_argument(
        "--output", required=True, help="Target path/identifier for the exported data"
    )

    failures_parser = subparsers.add_parser(
        "failures", help="Failure Corpus search and analysis utilities"
    )
    failures_sub = failures_parser.add_subparsers(dest="failures_command")
    failures_sub.add_parser(
        "search", help="Search for similar failures across the global corpus"
    ).add_argument("query", help="Search query string")

    drift_parser = subparsers.add_parser(
        "import-drift", help="Import production traces as new evaluation scenarios"
    )
    drift_parser.add_argument("--input", required=True, help="Path to production log or trace")
    drift_parser.add_argument(
        "--industry", required=True, help="Assume sector-specific schema for the import"
    )

    init_parser = subparsers.add_parser(
        "init", help="Scaffold a new benchmark environment and local industry registry"
    )
    init_parser.add_argument("--dir", help="Target directory for initialization")
    init_parser.add_argument("--industry", help="Primary industry sector to initialize")
    init_parser.add_argument(
        "--protocol", default="http", help="Default agent communication protocol"
    )
    init_parser.add_argument("--standard", help="Initial AES standard to adopt")
    init_parser.add_argument("--registry", help="Remote registry URL for scenario synchronization")

    subparsers.add_parser(
        "install", help="Install curated scenario packs for specific industrial benchmarks"
    ).add_argument("pack", help="Name of the scenario pack to install")

    plugin_parser = subparsers.add_parser(
        "plugin", help="Execute and manage plugin-specific subcommands"
    )
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command")
    plugin_sub.add_parser("list", help="List all registered and active plugins")
    plugin_reg = plugin_sub.add_parser("register", help="Register a new external plugin by path")
    plugin_reg.add_argument("path", help="File system path to the plugin directory")
    plugin_unreg = plugin_sub.add_parser("unregister", help="Unregister an existing plugin by name")
    plugin_unreg.add_argument("name", help="Identifier of the plugin to remove")

    registry_parser = subparsers.add_parser(
        "registry", help="Industry scenario registry management"
    )
    registry_sub = registry_parser.add_subparsers(dest="registry_command")
    registry_sub.add_parser(
        "sync", help="Synchronize the local registry with remote industry standards"
    )
    registry_add = registry_sub.add_parser(
        "add", help="Add a new scenario manifest to the local registry"
    )
    registry_add.add_argument("--id", required=True, help="Unique ID for the registry entry")
    registry_add.add_argument("--url", required=True, help="Source URL or path for the manifest")
    registry_sub.add_parser("search", help="Search the local and remote registries").add_argument(
        "query", help="Search string"
    )

    # Update the cache
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

        if not args.command:
            parser.print_help()
            return

        # [Audit BUG-04] Early initialization of run-log-dir to prevent FileNotFoundError
        run_log_dir = getattr(args, "run_log_dir", None)
        if run_log_dir and isinstance(run_log_dir, str):
            os.environ["RUN_LOG_DIR"] = run_log_dir
            Path(run_log_dir).mkdir(parents=True, exist_ok=True)

        # Dynamic imports for handlers to minimize footprint
        if args.command in [
            "evaluate",
            "run",
            "record",
            "playground",
            "replay",
            "verify",
            "certify",
            "gate",
            "quickstart",
        ]:
            from .handlers import evaluation as h

            if args.command == "evaluate":
                sys.exit(safe_run_async(h.handle_evaluate(args)) or 0)
            elif args.command == "run":
                sys.exit(safe_run_async(h.handle_run(args)) or 0)
            elif args.command == "record":
                sys.exit(safe_run_async(h.handle_record(args)) or 0)
            elif args.command == "playground":
                sys.exit(safe_run_async(h.handle_playground(args)) or 0)
            elif args.command == "replay":
                sys.exit(safe_run_async(h.handle_replay(args)) or 0)
            elif args.command == "verify":
                sys.exit(safe_run_async(h.handle_verify(args)) or 0)
            elif args.command == "certify":
                sys.exit(safe_run_async(h.handle_certify(args)) or 0)
            elif args.command == "gate":
                sys.exit(safe_run_async(h.handle_gate(args)) or 0)
            elif args.command == "quickstart":
                sys.exit(safe_run_async(h.handle_quickstart(args)) or 0)

        elif args.command in [
            "aes",
            "inspect",
            "lint",
            "list",
            "catalog-search",
            "catalog-refresh",
            "mutate",
            "scenario",
            "spec-to-eval",
            "import-drift",
        ]:
            from .handlers import scenarios as h

            if args.command == "aes":
                sys.exit(
                    safe_run_async(h.handle_aes_validate(args))
                    if args.aes_command == "validate"
                    else 0
                )
            elif args.command == "inspect":
                sys.exit(safe_run_async(h.handle_inspect(args)) or 0)
            elif args.command == "lint":
                sys.exit(safe_run_async(h.handle_lint(args)) or 0)
            elif args.command == "list":
                sys.exit(safe_run_async(h.handle_list(args)) or 0)
            elif args.command == "catalog-search":
                sys.exit(safe_run_async(h.handle_catalog_search(args)) or 0)
            elif args.command == "catalog-refresh":
                sys.exit(safe_run_async(h.handle_catalog_refresh(args)) or 0)
            elif args.command == "mutate":
                sys.exit(safe_run_async(h.handle_mutate(args)) or 0)
            elif args.command == "scenario":
                if args.scenario_command == "generate":
                    sys.exit(safe_run_async(h.handle_scenario_generate(args)) or 0)
                elif args.scenario_command == "inspect":
                    sys.exit(safe_run_async(h.handle_inspect(args)) or 0)
            elif args.command == "spec-to-eval":
                sys.exit(safe_run_async(h.handle_spec_to_eval(args)) or 0)
            elif args.command == "import-drift":
                sys.exit(safe_run_async(h.handle_import_drift(args)) or 0)

        elif args.command in [
            "calibrate",
            "explain",
            "leaderboard",
            "report",
            "taxonomy",
            "list-metrics",
        ]:
            from .handlers import analysis as h

            if args.command == "calibrate":
                sys.exit(safe_run_async(h.handle_calibrate(args)) or 0)
            elif args.command == "explain":
                sys.exit(safe_run_async(h.handle_explain(args)) or 0)
            elif args.command == "leaderboard":
                sys.exit(safe_run_async(h.handle_leaderboard(args)) or 0)
            elif args.command == "report":
                sys.exit(safe_run_async(h.handle_report(args)) or 0)
            elif args.command == "taxonomy":
                sys.exit(safe_run_async(h.handle_taxonomy(args)) or 0)
            elif args.command == "list-metrics":
                sys.exit(safe_run_async(h.handle_list_metrics(args)) or 0)

        elif args.command in [
            "analyze",
            "auto-translate",
            "ci",
            "cleanup-runs",
            "doctor",
            "export",
            "failures",
            "init",
            "install",
            "registry",
            "plugin",
            "list-plugins",
        ]:
            from .handlers import environment as h

            if args.command == "analyze":
                sys.exit(safe_run_async(h.handle_analyze(args)) or 0)
            elif args.command == "list-plugins":
                sys.exit(safe_run_async(h.handle_plugin_list(args)) or 0)
            elif args.command == "auto-translate":
                sys.exit(safe_run_async(h.handle_auto_translate(args)) or 0)
            elif args.command == "ci" and args.ci_command == "generate":
                sys.exit(safe_run_async(h.handle_ci_generate(args)) or 0)
            elif args.command == "cleanup-runs":
                sys.exit(safe_run_async(h.handle_cleanup_runs(args)) or 0)
            elif args.command == "doctor":
                sys.exit(safe_run_async(h.handle_doctor(args)) or 0)
            elif args.command == "export":
                sys.exit(safe_run_async(h.handle_export(args)) or 0)
            elif args.command == "failures" and args.failures_command == "search":
                sys.exit(safe_run_async(h.handle_failures_search(args)) or 0)
            elif args.command == "init":
                sys.exit(safe_run_async(h.handle_init(args)) or 0)
            elif args.command == "install":
                sys.exit(safe_run_async(h.handle_install(args)) or 0)
            elif args.command == "registry":
                if args.registry_command == "sync":
                    sys.exit(safe_run_async(h.handle_registry_sync(args)) or 0)
                elif args.registry_command == "add":
                    sys.exit(safe_run_async(h.handle_registry_add(args)) or 0)
                elif args.registry_command == "search":
                    sys.exit(safe_run_async(h.handle_registry_search(args)) or 0)
            elif args.command == "plugin":
                if args.plugin_command == "list":
                    sys.exit(safe_run_async(h.handle_plugin_list(args)) or 0)
                elif args.plugin_command == "register":
                    sys.exit(safe_run_async(h.handle_plugin_register(args)) or 0)
                elif args.plugin_command == "unregister":
                    sys.exit(safe_run_async(h.handle_plugin_unregister(args)) or 0)

        elif args.command == "console":
            from .console.app import run_server

            print(f"[CLI] Launching Visual Debugger on http://{args.host}:{args.port}")
            run_server(host=args.host, port=args.port, debug=args.debug)
            sys.exit(0)

        elif args.command == "contribute":
            from .contributor import ContributeWizard

            ContributeWizard.run()
            sys.exit(0)

        else:
            parser.print_help()

    except KeyboardInterrupt:
        print("\n[CLI] Interrupted.")
        sys.exit(130)
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # Industrial Hardening: Force explicit cleanup of all plugins (e.g. FlightRecorder handles)
        # This replaces the fragile __del__ pattern.
        from . import plugins

        plugins.manager.finalize()


if __name__ == "__main__":
    main()
