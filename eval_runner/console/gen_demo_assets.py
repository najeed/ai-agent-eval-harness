import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from eval_runner import config
from eval_runner.console.demo_traces import get_demo_trace, DEMO_IDS

def generate_assets():
    """
    Generates actual JSON artifacts in the runs/ folder for all demo IDs.
    Uses realistic timestamps relative to the current time.
    """
    run_dir = Path(config.RUN_LOG_DIR)
    run_dir.mkdir(parents=True, exist_ok=True)
    
    now = datetime.now()
    print(f"[*] Generating demo assets in {run_dir.absolute()}...")
    
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
            
        # Save to file
        file_path = run_dir / f"{run_id}.json"
        with open(file_path, "w") as f:
            json.dump(trace, f, indent=2)
            
        print(f" [+] Created {file_path.name} ({len(trace)} events)")

    print(f"\n[!] Success! Demo assets are now physically present on the system.")
    print(f"[!] You can now see these in the 'Historical Runs' section of the Console.")

if __name__ == "__main__":
    generate_assets()
