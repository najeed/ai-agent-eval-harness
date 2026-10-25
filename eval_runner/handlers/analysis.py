"""Post-run commands backed by the authoritative run provider."""

from __future__ import annotations

from .. import calibrator, leaderboard_generator, reporter, taxonomy
from ..explainer import explain_events
from ..trace_utils import reconstruct_results_from_events


def _events_for_run(run_id: str, *, run_store, context: dict | None = None) -> list[dict]:
    """Read a run through its explicit owner, never a vault path or resolver."""
    return run_store.get_events(run_id, offset=0, limit=10_000_000, context=context)


async def handle_report(args):
    run_id = getattr(args, "run_id", None)
    if not run_id:
        print("[CRITICAL] Run ID is mandatory for reporting.")
        return 1
    try:
        from eval_runner.runtime_services import resolve_run_store

        print(f"\n[Report] Generating stylized HTML for Run ID: {run_id}")
        events = _events_for_run(run_id, run_store=resolve_run_store())
        if not events:
            print(f"[ERROR] Run '{run_id}' was not found by the run provider.")
            return 1
        start = next((event for event in events if event.get("event") == "run_start"), {})
        metadata = start.get("metadata", {}) or {}
        scenario = {
            "metadata": {
                "id": metadata.get("id") or start.get("scenario", "unknown"),
                "name": metadata.get("name", "Untitled Report"),
            },
            "description": metadata.get("description", ""),
        }
        output = reporter.generate_html_report(
            scenario,
            reconstruct_results_from_events(events),
            metadata={"run_id": run_id, "evidence_source": "provider"},
            standalone=bool(getattr(args, "share", False)),
        )
        print(f"[OK] HTML Report generated: {output}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Report generation failed: {exc}")
        return 1


async def handle_explain(args):
    run_id = getattr(args, "run_id", None)
    if not run_id:
        print("[CRITICAL] Run ID is mandatory for explanation.")
        return 1
    try:
        from eval_runner.runtime_services import resolve_run_store

        events = _events_for_run(run_id, run_store=resolve_run_store())
        if not events:
            print(f"[ERROR] Run '{run_id}' was not found by the run provider.")
            return 1
        print(explain_events(events))
        return 0
    except Exception as exc:
        print(f"[ERROR] Explanation failed: {exc}")
        return 1


async def handle_calibrate(args):
    run_id = getattr(args, "run_id", None)
    if not run_id:
        print("[CRITICAL] Run ID is mandatory for calibration.")
        return 1
    try:
        from eval_runner.runtime_services import resolve_run_store

        print(f"\n[Calibrate] Measuring judge agreement for Run ID: {run_id}")
        events = _events_for_run(run_id, run_store=resolve_run_store())
        if not events:
            return 1
        return (
            calibrator.run_calibration_events(events, golden_path=getattr(args, "golden", None))
            or 0
        )
    except Exception as exc:
        print(f"❌ [ERROR] Calibration FAILED: {exc}")
        return 1


async def handle_leaderboard(args):
    try:
        leaderboard_generator.run_leaderboard(args.dir, args.output)
        return 0
    except Exception as exc:
        print(f"[ERROR] Leaderboard generation failed: {exc}")
        return 1


async def handle_taxonomy(args):
    try:
        print("\n" + "=" * 40)
        print(f"{'AGENTV FAILURE TAXONOMY':^40}")
        print("=" * 40)
        for category in taxonomy.CATEGORIES:
            print(f" - {category.replace('_', ' ').title()}")
        print("-" * 40)
        print("Use these tags in results to categorize failures.")
        print("=" * 40)
        return 0
    except Exception as exc:
        print(f"[ERROR] Taxonomy display failed: {exc}")
        return 1


async def handle_list_metrics(args):
    try:
        from ..metrics import MetricRegistry

        print("Registered Evaluation Metrics:")
        print("\n".join(MetricRegistry.list_metrics()))
        return 0
    except Exception as exc:
        print(f"[ERROR] Metric listing failed: {exc}")
        return 1


async def handle_trend(args):
    try:
        from ..trend import RunTrendAnalyzer

        print(f"\n[Trend] Analyzing historical runs in: {args.run_log_dir}")
        analyzer = RunTrendAnalyzer(
            run_log_dir=args.run_log_dir,
            agent_name=args.agent_name,
            window=args.window,
            threshold=args.threshold,
        )
        reports = analyzer.analyze()

        if not reports:
            print("⚠️  [Trend] No matching runs or agents found to analyze.")
            return 0

        any_regression = False
        print("\n" + "=" * 60)
        print(f"{'AGENT PERFORMANCE TREND ANALYSIS':^60}")
        print("=" * 60)

        for r in reports:
            print(f"Agent: {r.agent_name}")
            print(f"  Window size: {r.window} runs")
            print(f"  OLS Slope:   {r.slope:+.5f}")
            print(f"  Direction:   {r.direction.upper()}")
            print("  Run Details:")
            for pt in r.run_points:
                print(f"    - {pt.run_id} ({pt.timestamp}): pass_rate = {pt.pass_rate:.2%}")

            if r.any_regression:
                any_regression = True
                print("  🚨 REGRESSION DETECTED!")
            print("-" * 60)

        if any_regression and getattr(args, "exit_on_regression", False):
            print(
                "\n❌ [Trend] Regression detected under specified threshold. Exiting with code 1."
            )
            return 1

        print("\n[OK] Trend analysis completed successfully.")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Trend analysis FAILED: {e}")
        return 1
