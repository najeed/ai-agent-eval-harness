"""
eval_runner.reference.inprocess_backend
OSS Reference Implementation: InProcessExecutionBackend
"""

import threading
from typing import Any

from eval_runner.interfaces.backend import ExecutionBackend


class InProcessExecutionBackend(ExecutionBackend):
    """
    In-process reference execution backend for local evaluation runs.
    Executes directly within the current Python process either synchronously or
    asynchronously via thread.
    """

    def __init__(self):
        self._active_runs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        run_id: str,
        scenario_data: dict[str, Any],
        background: bool = False,
        **kwargs: Any,
    ) -> Any:
        import eval_runner.runner as runner

        with self._lock:
            self._active_runs[run_id] = {
                "status": "RUNNING",
                "scenario": scenario_data.get("metadata", {}).get("name", run_id),
                "scenario_data": scenario_data,
                "kwargs": kwargs,
            }

        def _execute():
            try:
                results = runner.run_scenario(scenario_data, run_id=run_id, **kwargs)
                with self._lock:
                    if run_id in self._active_runs:
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
            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = "ABORTED"
                self._active_runs[run_id]["cancel_reason"] = reason or "Cancelled by user"
                return True
            return False

    def resume(self, run_id: str, resumption_token: str | None = None, **kwargs: Any) -> Any:
        """Resumes a paused evaluation run using session state and resumption token."""
        with self._lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = "RUNNING"
                self._active_runs[run_id]["resumption_token"] = resumption_token
                return self._active_runs[run_id]
        return None
