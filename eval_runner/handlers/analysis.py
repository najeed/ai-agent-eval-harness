"""
handlers/analysis.py

Post-run utility handlers (reports, explainers, etc.)
"""

import logging

from .. import (
    calibrator,
    explainer,
    leaderboard_generator,
    reporter,
    taxonomy,
    trace_utils,
)
from ..trace_utils import reconstruct_results_from_events

logger = logging.getLogger(__name__)


async def handle_report(args):
    """
    Handler for 'report' command.
    Generates a stylized HTML report from an industrial run trace.
    """
    try:
        from .evaluation import _ensure_path_safe, _resolve_replay_trace

        run_id = args.run_id
        if not run_id:
            print("      [CRITICAL] FAILED: Run ID is mandatory for reporting.")
            return 1

        trace_path = _resolve_replay_trace(run_id)
        if not trace_path or not _ensure_path_safe(trace_path, "Report Trace"):
            return 1

        print(f"\n[Report] Generating stylized HTML for Run ID: {run_id}")

        # Load and Reconstruction logic (Industry Standard)
        events = trace_utils.load_events(trace_path)
        run_start = next((e for e in events if e.get("event") == "run_start"), {})
        metadata = run_start.get("metadata", {})

        scenario = {
            "metadata": {
                "id": metadata.get("id") or run_start.get("scenario", "unknown"),
                "name": metadata.get("name", "Untitled Report"),
            },
            "description": metadata.get("description", ""),
        }
        results = reconstruct_results_from_events(events)

        html_path = reporter.generate_html_report(
            scenario,
            results,
            metadata={"trace_path": str(trace_path)},
            standalone=getattr(args, "share", False),
        )
        print(f"[OK] HTML Report generated: {html_path}")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Report generation FAILED: {e}")
        return 1


async def handle_explain(args):
    """Handler for 'explain' command."""
    try:
        from .evaluation import _ensure_path_safe, _resolve_replay_trace

        run_id = args.run_id
        if not run_id:
            print("      [CRITICAL] FAILED: Run ID is mandatory for explanation.")
            return 1

        trace_path = _resolve_replay_trace(run_id)
        if not trace_path or not _ensure_path_safe(trace_path, "Explanation Trace"):
            return 1

        print(f"\n[Explain] Diagnosing Run ID: {run_id}")
        # explainer.explain_trace is the industrial standard method (explainer.py:L6)
        explainer.explain_trace(trace_path)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Explanation FAILED: {e}")
        return 1


async def handle_calibrate(args):
    """Handler for 'calibrate' command."""
    try:
        from .evaluation import _ensure_path_safe, _resolve_replay_trace

        run_id = args.run_id
        if not run_id:
            print("      [CRITICAL] FAILED: Run ID is mandatory for calibration.")
            return 1

        trace_path = _resolve_replay_trace(run_id)
        if not trace_path or not _ensure_path_safe(trace_path, "Calibration Trace"):
            return 1

        print(f"\n[Calibrate] Measuring judge agreement for Run ID: {run_id}")
        # calibrator.run_calibration (calibrator.py:L11)
        calibrator.run_calibration(str(trace_path), golden_path=getattr(args, "golden", None))
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Calibration FAILED: {e}")
        return 1


async def handle_leaderboard(args):
    """Handler for 'leaderboard' command."""
    try:
        leaderboard_generator.run_leaderboard(args.dir, args.output)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Leaderboard generation FAILED: {e}")
        return 1


async def handle_taxonomy(args):
    """Handler for 'taxonomy' command."""
    try:
        print("\n" + "=" * 40)
        print(f"{'AGENTV FAILURE TAXONOMY':^40}")
        print("=" * 40)
        for cat in taxonomy.CATEGORIES:
            print(f" - {cat.replace('_', ' ').title()}")
        print("-" * 40)
        print("Use these tags in results to categorize failures.")
        print("=" * 40)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Taxonomy display FAILED: {e}")
        return 1


async def handle_list_metrics(args):
    """Handler for 'list-metrics' command."""
    try:
        from ..metrics import MetricRegistry

        print("\nRegistered Evaluation Metrics:")
        for metric in MetricRegistry.list_metrics():
            print(f" - {metric}")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Failed to list metrics: {e}")
        return 1
