"""
flight_recorder.py

A built-in plugin that subscribes to EventEmitter to record run traces.
This decouples logging from the core engine loop.
"""

import os
import json
from pathlib import Path
from .plugins import BaseEvalPlugin
from .events import EventEmitter, CoreEvents, Event

class FlightRecorderPlugin(BaseEvalPlugin):
    """Subscribes to all core events and writes them to run.jsonl files."""

    def __init__(self):
        self.log_dir = Path(os.getenv("RUN_LOG_DIR", "runs"))
        self.per_run = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
        self.master = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"
        self.run_id = "unknown"
        self.master_log_path = self.log_dir / "run.jsonl"
        self.per_run_log_path = None
        self.log_rotate_count = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))

        # Subscribe to the event bus
        EventEmitter.subscribe(self.handle_event)

    def handle_event(self, event: Event):
        """Callback for EventEmitter."""
        data = event.to_dict()
        
        # Special handling for RUN_START to set paths
        if event.name == CoreEvents.RUN_START:
            self.run_id = data.get("run_id", "unknown")
            self.per_run_log_path = self.log_dir / f"{self.run_id}.jsonl"
            self.log_dir.mkdir(parents=True, exist_ok=True)
            
            # Perform rotation if configured
            if self.log_rotate_count > 0:
                self.rotate_logs()

        # Serialize and write
        content = json.dumps(data) + "\n"
        
        if self.per_run and self.per_run_log_path:
            with open(self.per_run_log_path, "a", encoding="utf-8") as f:
                f.write(content)
        
        if self.master:
            with open(self.master_log_path, "a", encoding="utf-8") as f:
                f.write(content)

    def rotate_logs(self):
        """Keeps only the latest N run-<id>.jsonl files."""
        run_files = sorted(
            self.log_dir.glob("*.jsonl"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        # Exclude the master log if it exists
        run_files = [f for f in run_files if f.name != "run.jsonl"]
        
        if len(run_files) > self.log_rotate_count:
            for old_file in run_files[self.log_rotate_count:]:
                try:
                    old_file.unlink()
                    print(f"      [FlightRecorder] Rotated old log: {old_file.name}")
                except Exception as e:
                    print(f"      [FlightRecorder] Error rotating log {old_file}: {e}")

    # Note: methods like before_evaluation are still available if needed
    # but handle_event covers most needs for the Flight Recorder.
