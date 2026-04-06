"""
flight_recorder.py

A built-in plugin that subscribes to EventEmitter to record run traces.
This decouples logging from the core engine loop.
"""

import json
import os
from pathlib import Path
from datetime import datetime


from .events import CoreEvents, Event, EventEmitter
from .plugins import BaseEvalPlugin


class FlightRecorderPlugin(BaseEvalPlugin):
    """Subscribes to all core events and writes them to run.jsonl files."""

    def __init__(self):
        import eval_runner.config as config
        self.log_dir = Path(os.getenv("RUN_LOG_DIR", config.RUN_LOG_DIR))
        self.per_run = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
        self.master = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"
        self.run_id = "unknown"
        self.master_log_path = self.log_dir / "run.jsonl"
        self.per_run_log_path = None
        self.log_rotate_count = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))

        # [Iteration 4: Compliance DNA]
        self._sequence_number = 0
        self._private_key_path = os.getenv("EVAL_SIGNING_KEY")
        self._audit_level = int(os.getenv("AUDIT_LEVEL", "2"))

        # Subscribe to the event bus
        EventEmitter.subscribe(self.handle_event)

    def handle_event(self, event: Event):
        """Callback for EventEmitter."""
        import eval_runner.verifier as verifier
        
        data = event.to_dict()
        
        # [Iteration 4: Compliance DNA]
        self._sequence_number += 1
        data["_seq"] = self._sequence_number
        data["_ts_iso"] = datetime.now().astimezone().isoformat()

        # Special handling for RUN_START to set paths
        if event.name == CoreEvents.RUN_START:
            self.run_id = data.get("run_id", "unknown")
            self.per_run_log_path = self.log_dir / f"{self.run_id}.jsonl"
            self.log_dir.mkdir(parents=True, exist_ok=True)

            if self.log_rotate_count > 0:
                self.rotate_logs()

        # [Iteration 4: Signing]
        if self._audit_level >= 2 and self._private_key_path:
            try:
                # Sign the stable JSON representation
                payload = json.dumps(data, sort_keys=True).encode("utf-8")
                data["_sig"] = verifier.TraceVerifier.sign_asymmetric(payload, self._private_key_path)
            except Exception as e:
                data["_sig_error"] = str(e)

        # Serialize and write
        content = json.dumps(data) + "\n"

        if self.per_run and self.per_run_log_path:
            with open(self.per_run_log_path, "a", encoding="utf-8") as f:
                f.write(content)

        if self.master:
            with open(self.master_log_path, "a", encoding="utf-8") as f:
                f.write(content)

            # --- Master Log Rotation (Industrial Hygiene) ---
            from . import config

            limit = config.RUN_LOG_MASTER_LIMIT
            if limit > 0:
                try:
                    # check file size or line count occasionally?
                    # For simplicity, we ensure the file doesn't explode in the background.
                    # In a production setting, this would be a RotatingFileHandler.
                    # Here we implement a manual "tail" truncation if limit is exceeded.
                    with open(self.master_log_path, encoding="utf-8") as rf:
                        lines = rf.readlines()

                    if len(lines) > limit + 50:  # Buffer to avoid constant rewriting
                        print(
                            f"      [FlightRecorder] Rotating master log (Current: {len(lines)} entries, Limit: {limit})"  # noqa: E501
                        )
                        with open(self.master_log_path, "w", encoding="utf-8") as wf:
                            wf.writelines(lines[-limit:])
                except Exception as e:
                    print(f"      [FlightRecorder] Rotation failed: {e}")

    def rotate_logs(self):
        """Keeps only the latest N run-<id>.jsonl files."""
        run_files = sorted(
            self.log_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True
        )

        # Exclude the master log if it exists, and only target files (not directories)
        run_files = [f for f in run_files if f.name != "run.jsonl" and f.is_file()]

        if len(run_files) > self.log_rotate_count:
            for old_file in run_files[self.log_rotate_count :]:
                try:
                    old_file.unlink()
                    print(f"      [FlightRecorder] Rotated old log: {old_file.name}")
                except Exception as e:
                    print(f"      [FlightRecorder] Error rotating log {old_file}: {e}")

    def flush(self):
        """Pass-through for API compatibility (writes are synchronous)."""
        pass

    # Note: methods like before_evaluation are still available if needed
    # but handle_event covers most needs for the Flight Recorder.
