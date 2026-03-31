"""
handlers/analysis.py

Post-run utility handlers (reports, explainers, etc.)
"""

import json
from pathlib import Path
from typing import Dict, Any
from .. import reporter, calibrator, explainer, leaderboard_generator, taxonomy, trace_utils
from ..cli import reconstruct_results_from_events

def handle_report(args):
    """Handler for 'report' command."""
    print(f"\n[Report] Generating HTML report from: {args.path}")
    path = Path(args.path)
    if not path.exists():
        print(f"[ERROR] Trace file not found at {path}")
        return

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

    html_path = reporter.generate_html_report(scenario, results, metadata={"trace_path": str(path)}, standalone=getattr(args, "share", False))
    print(f"[OK] HTML Report generated: {html_path}")

def handle_explain(args):
    """Handler for 'explain' command."""
    trace_path = Path(args.path)
    explainer.explain_trace(str(trace_path))

def handle_calibrate(args):
    """Handler for 'calibrate' command."""
    calibrator.run_calibration(args.path, plot=getattr(args, "plot", False))

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

