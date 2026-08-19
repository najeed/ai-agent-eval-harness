"""
eval_runner.reference.inprocess_backend
OSS Reference Implementation: InProcessExecutionBackend
"""

from __future__ import annotations

import threading
from typing import Any

from eval_runner.interfaces.backend import ExecutionBackend
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore


class InProcessExecutionBackend(ExecutionBackend):
    """
    In-process reference execution backend for local evaluation runs.
    Executes directly within the current Python process either synchronously or
    asynchronously via thread with real cancellation token propagation and checkpoint resumption.
    """

    _instance: InProcessExecutionBackend | None = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls, checkpoint_store: Any | None = None) -> InProcessExecutionBackend:
        """Returns the shared application singleton execution backend instance."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(checkpoint_store=checkpoint_store)
            return cls._instance

    @classmethod
    def clear_instance(cls) -> None:
        """Resets singleton instance for test isolation."""
        with cls._singleton_lock:
            cls._instance = None

    def __init__(self, checkpoint_store: Any | None = None):
        self._active_runs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancellation_events: dict[str, threading.Event] = {}
        self._checkpoint_store = checkpoint_store
        self._lock = threading.Lock()

    @property
    def checkpoint_store(self):
        if self._checkpoint_store is None:
            self._checkpoint_store = SQLiteCheckpointStore()
        return self._checkpoint_store

    def submit(
        self,
        run_id: str,
        scenario_data: dict[str, Any],
        background: bool = False,
        cancellation_event: threading.Event | None = None,
        resumption_checkpoint: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        import eval_runner.runner as runner

        cancel_ev = cancellation_event or threading.Event()
        with self._lock:
            self._cancellation_events[run_id] = cancel_ev
            self._active_runs[run_id] = {
                "status": "RUNNING",
                "scenario": scenario_data.get("metadata", {}).get("name", run_id),
                "scenario_data": scenario_data,
                "kwargs": kwargs,
                "resumption_checkpoint": resumption_checkpoint,
            }

        def _execute():
            try:
                results = runner.run_scenario(
                    scenario_data,
                    run_id=run_id,
                    cancellation_event=cancel_ev,
                    resumption_checkpoint=resumption_checkpoint,
                    **kwargs,
                )
                with self._lock:
                    if run_id in self._active_runs:
                        if cancel_ev.is_set():
                            self._active_runs[run_id]["status"] = "ABORTED"
                        else:
                            self._active_runs[run_id]["status"] = "COMPLETED"
                        self._active_runs[run_id]["results"] = results
                return results
            except Exception as e:
                with self._lock:
                    if run_id in self._active_runs:
                        self._active_runs[run_id]["status"] = "FAILED"
                        self._active_runs[run_id]["error"] = str(e)
                raise

        if background:
            t = threading.Thread(target=_execute, name=f"eval-{run_id}", daemon=True)
            with self._lock:
                self._threads[run_id] = t
            t.start()
            return {"status": "started", "run_id": run_id}
        else:
            return _execute()

    def status(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return self._active_runs.get(run_id, {"status": "UNKNOWN"})

    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        with self._lock:
            if run_id in self._cancellation_events:
                self._cancellation_events[run_id].set()
            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = "ABORTED"
                self._active_runs[run_id]["cancel_reason"] = reason or "Cancelled by user"
                return True
            return False

    def resume(self, run_id: str, resumption_token: str | None = None, **kwargs: Any) -> Any:
        """Resumes a paused evaluation run using session state and resumption token."""
        checkpoint = self.checkpoint_store.load(run_id)
        if not checkpoint and run_id in self._active_runs:
            checkpoint = self._active_runs[run_id].get("resumption_checkpoint")

        with self._lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = "RUNNING"
                self._active_runs[run_id]["resumption_token"] = resumption_token
                if not checkpoint and not kwargs.get("force_submit", False):
                    return self._active_runs[run_id]

        if not checkpoint and run_id not in self._active_runs:
            return None

        scenario_data = (
            (checkpoint.get("scenario_data") if checkpoint else None)
            or (
                self._active_runs.get(run_id, {}).get("scenario_data")
                if run_id in self._active_runs
                else None
            )
            or {"metadata": {"name": run_id}, "id": run_id, "workflow": [{"id": "resumed_task"}]}
        )

        background = kwargs.pop("background", False)
        return self.submit(
            run_id=run_id,
            scenario_data=scenario_data,
            background=background,
            resumption_checkpoint=checkpoint,
            **kwargs,
        )
