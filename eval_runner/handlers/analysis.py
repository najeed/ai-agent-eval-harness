"""
handlers/analysis.py

Post-run utility handlers (reports, explainers, etc.)
"""

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

    # --- [TIERED RESOLUTION] ---
    # 1. Primary: Industrial Vault (Mandatory for AES v1.5.0)
    vault_path = (config.RUN_LOG_DIR / run_id / "run.jsonl").resolve()
    # 2. Fallback: Master Log (Industrial Consolidation)
    master_path = (config.RUN_LOG_DIR / "run.jsonl").resolve()

    events = []
    if vault_path.exists():
        path = vault_path
        events = trace_utils.load_events(path)
    elif master_path.exists():
        # [RECOVERABLE FALLBACK] Vault missing but master log available
        try:
            all_events = trace_utils.load_events(master_path)
            events = [e for e in all_events if e.get("run_id") == run_id]

            if events:
                print(
                    "❌ [ERROR] Vault directory not found for Run ID "
                    f"'{run_id}'. Falling back to master log..."
                )
                path = master_path
            else:
                print(
                    f"❌ [ERROR] Run ID '{run_id}' not found in vault or "
                    "master log. Please verify the Run ID."
                )
                return
        except Exception as e:
            print(f"❌ [ERROR] Failed to load master log: {e}")
            return
    else:
        print(f"❌ [ERROR] Trace file for Run ID '{run_id}' not found in vault or master log.")
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

    # --- [TIERED RESOLUTION] ---
    # 1. Primary: Industrial Vault
    vault_path = (config.RUN_LOG_DIR / run_id / "run.jsonl").resolve()
    # 2. Fallback: Master Log
    master_path = (config.RUN_LOG_DIR / "run.jsonl").resolve()

    trace_path = None
    if vault_path.exists():
        trace_path = vault_path
    elif master_path.exists():
        # [RECOVERABLE FALLBACK] Passing master path to explain_trace
        try:
            all_events = trace_utils.load_events(master_path)
            if any(e.get("run_id") == run_id for e in all_events):
                print(
                    "❌ [ERROR] Vault directory not found for Run ID "
                    f"'{run_id}'. Using master log fallback."
                )
                trace_path = master_path
            else:
                print(f"❌ [ERROR] Run ID '{run_id}' not found in vault or master log.")
                return
        except Exception as e:
            print(f"❌ [ERROR] Failed to load master log: {e}")
            return
    else:
        print(f"❌ [ERROR] Trace file for Run ID '{run_id}' not found.")
        return

    explainer.explain_trace(str(trace_path), run_id=run_id)


def handle_calibrate(args):
    """Handler for 'calibrate' command."""
    from .. import config

    run_id = args.run_id

    # --- [TIERED RESOLUTION] ---
    vault_path = (config.RUN_LOG_DIR / run_id / "run.jsonl").resolve()
    master_path = (config.RUN_LOG_DIR / "run.jsonl").resolve()

    trace_path = None
    if vault_path.exists():
        trace_path = vault_path
    elif master_path.exists():
        try:
            all_events = trace_utils.load_events(master_path)
            if any(e.get("run_id") == run_id for e in all_events):
                print(
                    "❌ [ERROR] Vault directory not found for Run ID "
                    f"'{run_id}'. Using master log fallback."
                )
                trace_path = master_path
            else:
                print(f"❌ [ERROR] Run ID '{run_id}' not found in vault or master log.")
                return
        except Exception as e:
            print(f"❌ [ERROR] Failed to load master log: {e}")
            return
    else:
        print(f"❌ [ERROR] Trace file for Run ID '{run_id}' not found.")
        return

    calibrator.run_calibration(
        str(trace_path),
        run_id=run_id,
        golden_path=getattr(args, "golden", None),
        plot=getattr(args, "plot", False),
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
