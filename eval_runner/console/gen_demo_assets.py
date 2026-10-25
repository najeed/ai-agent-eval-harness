from datetime import datetime, timedelta

from eval_runner.console.demo_traces import DEMO_IDS, get_demo_trace


def generate_assets(run_store=None):
    """
    Populates demo evidence through the authoritative run provider.
    Uses realistic timestamps relative to the current time.
    """
    if run_store is None:
        from eval_runner.runtime_services import resolve_run_store

        run_store = resolve_run_store()
    now = datetime.now()
    print("[*] Generating provider-owned demo evidence...")

    for i, run_id in enumerate(DEMO_IDS):
        trace = get_demo_trace(run_id)
        if not trace:
            continue

        # Shift timestamps to look like they happened recently
        # Each run happened 1 hour apart, ending 5 minutes ago
        time_offset = timedelta(hours=(len(DEMO_IDS) - i), minutes=5)
        base_time = now - time_offset

        # Update trace timestamps
        for j, event in enumerate(trace):
            # Add a few seconds between events
            event_time = base_time + timedelta(seconds=j * 2)
            event["timestamp"] = event_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        run_store.create_run(run_id, scenario_id="demo", status="OPEN")
        run_store.append_events(run_id, trace)
        run_store.update_run_status(run_id, "COMPLETED")
        print(f" [+] Created provider run {run_id} ({len(trace)} events)")

    print("\n[!] Success! Demo runs are available through the active provider.")


if __name__ == "__main__":
    generate_assets()
