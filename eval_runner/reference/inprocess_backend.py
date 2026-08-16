"""
eval_runner.reference.inprocess_backend
OSS Reference Implementation: InProcessExecutionBackend
"""

from typing import Any

import eval_runner.runner as runner
from eval_runner.interfaces.backend import ExecutionBackend


class InProcessExecutionBackend(ExecutionBackend):
    """
    In-process reference execution backend for local evaluation runs.
    Executes directly within the current Python process.
    """

    def __init__(self):
        self._active_runs: dict[str, dict[str, Any]] = {}

    def submit(self, run_id: str, scenario_data: dict[str, Any], **kwargs: Any) -> Any:
        self._active_runs[run_id] = {
            "status": "RUNNING",
            "scenario": scenario_data.get("metadata", {}).get("name", run_id),
        }
        try:
            results = runner.run_scenario(scenario_data, run_id=run_id, **kwargs)
            self._active_runs[run_id]["status"] = "COMPLETED"
            self._active_runs[run_id]["results"] = results
            return results
        except Exception as e:
            self._active_runs[run_id]["status"] = "FAILED"
            self._active_runs[run_id]["error"] = str(e)
            raise

    def status(self, run_id: str) -> dict[str, Any]:
        return self._active_runs.get(run_id, {"status": "UNKNOWN"})

    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        if run_id in self._active_runs:
            self._active_runs[run_id]["status"] = "ABORTED"
            self._active_runs[run_id]["cancel_reason"] = reason or "Cancelled by user"
            return True
        return False

    def resume(self, run_id: str, resumption_token: str | None = None, **kwargs: Any) -> Any:
        # Reference resumption logic
        if run_id in self._active_runs:
            self._active_runs[run_id]["status"] = "RUNNING"
            self._active_runs[run_id]["resumption_token"] = resumption_token
            return self._active_runs[run_id]
        return None
