"""
handlers/analysis.py

Post-run utility handlers (reports, explainers, etc.)
"""

from pathlib import Path

from .. import calibrator, explainer, leaderboard_generator, reporter, taxonomy, trace_utils
from ..trace_utils import reconstruct_results_from_events


def handle_report(args):
    """
    Handler for 'report' command.
    Generates a stylized HTML report from an industrial run trace.
    """
    from .. import config

    # --- [SSOT] Mandatory Run ID Resolution ---
    run_id = args.run_id
    if not run_id:
        print("      [CRITICAL] FAILED: Run ID is mandatory for reporting.")
        return

    # Resolve from authoritative vault
    run_log_dir = (config.RUN_LOG_DIR / run_id).resolve()
    path = run_log_dir / "run.jsonl"
    
    if not path.exists():
        # Fallback for flat traces
        flat_trace = (config.RUN_LOG_DIR / f"{run_id}.jsonl").resolve()
        if flat_trace.exists():
            path = flat_trace
        else:
            print(f"      [CRITICAL] FAILED: Trace file for {run_id} not found.")
            return

    print(f"\n[Report] Generating HTML report from Run ID: {run_id}")
    
    events = trace_utils.load_events(path)
    run_start = next((e for e in events if e.get("event") == "run_start"), {})
    metadata = run_start.get("metadata", {})

    scenario = {
        "metadata": {
            "id": metadata.get("id") or run_start.get("scenario", "unknown"),
            "name": metadata.get("name", "Untitled Report"),
            "industry": metadata.get("industry", "N/A"),
        },
        "description": metadata.get("description", ""),
    }

    # Reconstruct results from events
    results = reconstruct_results_from_events(events)

    html_path = reporter.generate_html_report(
        scenario,
        results,
        metadata={"trace_path": str(path)},
        standalone=getattr(args, "share", False),
    )
    print(f"[OK] HTML Report generated: {html_path}")


def handle_explain(args):
    """Handler for 'explain' command."""
    from .. import config
    run_id = args.run_id
    
    # Resolve from authoritative vault
    run_log_dir = (config.RUN_LOG_DIR / run_id).resolve()
    trace_path = run_log_dir / "run.jsonl"
    
    if not trace_path.exists():
        flat_trace = (config.RUN_LOG_DIR / f"{run_id}.jsonl").resolve()
        if flat_trace.exists():
            trace_path = flat_trace
        else:
            print(f"      [CRITICAL] FAILED: Trace file for {run_id} not found.")
            return

    explainer.explain_trace(str(trace_path))


def handle_calibrate(args):
    """Handler for 'calibrate' command."""
    from .. import config
    run_id = args.run_id
    
    # Resolve from authoritative vault
    run_log_dir = (config.RUN_LOG_DIR / run_id).resolve()
    trace_path = run_log_dir / "run.jsonl"
    
    if not trace_path.exists():
        flat_trace = (config.RUN_LOG_DIR / f"{run_id}.jsonl").resolve()
        if flat_trace.exists():
            trace_path = flat_trace
        else:
            print(f"      [CRITICAL] FAILED: Trace file for {run_id} not found.")
            return

    calibrator.run_calibration(
        str(trace_path), golden_path=getattr(args, "golden", None), plot=getattr(args, "plot", False)
    )


def handle_leaderboard(args):
    """Handler for 'leaderboard' command."""
    leaderboard_generator.run_leaderboard(args.dir, args.output)


def handle_taxonomy(args):
    """Handler for 'taxonomy' command."""
    print("\n" + "=" * 40)
    print(f"{'AGENT-EVAL FAILURE TAXONOMY':^40}")
    print("=" * 40)
    for cat in taxonomy.CATEGORIES:
        print(f" - {cat.replace('_', ' ').title()}")
    print("-" * 40)
    print("Use these tags in results to categorize failures.")
    print("=" * 40)


def handle_list_metrics(args):
    """Handler for 'list-metrics' command."""
    from ..metrics import MetricRegistry

    print("\nRegistered Metrics:")
    for name in MetricRegistry._metrics.keys():
        print(f" - {name}")
