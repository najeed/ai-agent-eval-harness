"""
flight_recorder.py

A built-in plugin that subscribes to EventEmitter to record run traces.
This decouples logging from the core engine loop.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .events import CoreEvents, Event
from .plugins import BaseEvalPlugin


class FlightRecorderPlugin(BaseEvalPlugin):
    """Subscribes to all core events and writes them to run.jsonl files."""

    def __init__(self):
        import eval_runner.config as config

        self.log_dir = Path(os.getenv("RUN_LOG_DIR", str(config.RUN_LOG_DIR)))
        self.per_run = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
        self.master = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"
        self.run_id = "unknown"
        self.master_log_path = self.log_dir / "run.jsonl"
        self.per_run_log_path = None
        self.log_rotate_count = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))

        # State-aware handles for Windows stability
        self._handles = {}

        # [Iteration 4: Compliance DNA]
        self._sequence_number = 0
        self._private_key_path = os.getenv("EVAL_SIGNING_KEY")
        self._audit_level = int(os.getenv("AUDIT_LEVEL", "2"))

        from . import events

        # Subscribe to the event bus
        events.subscribe(self.handle_event)

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
            # [Refresher] Re-read environment variables for dynamic runtime configuration
            import eval_runner.config as config

            self.log_dir = Path(os.getenv("RUN_LOG_DIR", str(config.RUN_LOG_DIR)))
            self.per_run = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
            self.master = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"
            self.log_rotate_count = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))
            self.master_log_path = self.log_dir / "run.jsonl"

            self.run_id = data.get("run_id", "unknown")
            self.per_run_log_path = self.log_dir / f"{self.run_id}.jsonl"
            self.log_dir.mkdir(parents=True, exist_ok=True)

            if self.log_rotate_count > 0:
                self.rotate_logs()

        # [Iteration 4: Signing] Trace-level integrity
        if self._audit_level >= 2 and self._private_key_path:
            try:
                payload = json.dumps(data, sort_keys=True).encode("utf-8")
                data["_sig"] = verifier.TraceVerifier.sign_payload(payload, self._private_key_path)
            except Exception as e:
                data["_sig_error"] = str(e)

        # Serialize and write
        content = json.dumps(data) + "\n"

        def _write_buffered(path, content):
            # [WinHardening] Persistent handles to bypass WinError 145/F-Lock contention
            if str(path) not in self._handles:
                self._handles[str(path)] = open(path, "a", encoding="utf-8", buffering=1)
            self._handles[str(path)].write(content)

        try:
            if self.per_run and self.per_run_log_path:
                _write_buffered(self.per_run_log_path, content)

            if self.master:
                _write_buffered(self.master_log_path, content)
        except Exception as e:
            sys.stderr.write(f"   [FlightRecorder] [ERROR] File I/O Error: {e}\n")

    def finalize_run(self):
        """
        Explicitly closes file handles and flushes telemetry to disk.
        Critical for resolving Windows file-lock races.
        """
        for path_str, handle in self._handles.items():
            try:
                handle.flush()
                # [Staff Requirement] Force physical sync to prevent metadata corruption on crash
                os.fsync(handle.fileno())
                handle.close()
            except (AttributeError, ImportError, ValueError) as shut_e:
                # Guard against shutdown races where os or handles are already cleared
                # but log for forensic visibility in debug mode
                sys.stderr.write(
                    f"   [FlightRecorder] [DEBUG] Shutdown race in finalize: {shut_e}\n"
                )
            except Exception as e:
                sys.stderr.write(
                    f"   [FlightRecorder] [WARNING] Finalization error on {path_str}: {e}\n"
                )
        self._handles.clear()

    def after_evaluation(
        self, context: Any, results: list, span_context: dict[str, Any] | None = None
    ):
        """
        Core Hook: Lifecycle aware finalization.
        This is called by the engine before the evaluator returns control.
        """
        self.finalize_run()

    def rotate_logs(self):
        """Keeps only the latest N run-<id>.jsonl files."""
        run_files = sorted(
            self.log_dir.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True
        )
        run_files = [f for f in run_files if f.name != "run.jsonl" and f.is_file()]

        if len(run_files) > self.log_rotate_count:
            for old_file in run_files[self.log_rotate_count :]:
                try:
                    old_file.unlink()
                except Exception as e:
                    sys.stderr.write(
                        f"   [FlightRecorder] [WARNING] Error rotating log {old_file.name}: {e}\n"
                    )

    def flush(self):
        """Explicit flush trigger."""
        for handle in self._handles.values():
            try:
                handle.flush()
                os.fsync(handle.fileno())
            except Exception as e:
                sys.stderr.write(f"   [FlightRecorder] [WARNING] Flush error: {e}\n")

    # Note: methods like before_evaluation are still available if needed
    # but handle_event covers most needs for the Flight Recorder.
