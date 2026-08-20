"""
eval_runner.reference.inprocess_backend
OSS Reference Implementation: InProcessExecutionBackend (v2.0.0).

Executes evaluation runs within the current process with thread isolation,
strict execution state machine enforcement, and full dependency graph injection.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from eval_runner.interfaces.backend import ExecutionBackend
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore


class InProcessExecutionBackend(ExecutionBackend):
    """
    In-process reference execution backend for local evaluation runs.
    Executes directly within the current Python process either synchronously or
    asynchronously via thread with real cancellation token propagation, state machine guards,
    and checkpoint resumption.
    """

    _instance: InProcessExecutionBackend | None = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(
        cls,
        checkpoint_store: Any | None = None,
        runner: Any | None = None,
        artifact_store: Any | None = None,
        policy_evaluator: Any | None = None,
        signing_backend: Any | None = None,
        config_resolver: Any | None = None,
        run_store: Any | None = None,
    ) -> InProcessExecutionBackend:
        """Returns the shared application singleton execution backend instance."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(
                    checkpoint_store=checkpoint_store,
                    runner=runner,
                    artifact_store=artifact_store,
                    policy_evaluator=policy_evaluator,
                    signing_backend=signing_backend,
                    config_resolver=config_resolver,
                    run_store=run_store,
                )
            else:
                # Update any freshly provided injected dependencies
                cls._instance.set_dependency_graph(
                    checkpoint_store=checkpoint_store,
                    runner=runner,
                    artifact_store=artifact_store,
                    policy_evaluator=policy_evaluator,
                    signing_backend=signing_backend,
                    config_resolver=config_resolver,
                    run_store=run_store,
                )
            return cls._instance

    @classmethod
    def clear_instance(cls) -> None:
        """Resets singleton instance for test isolation."""
        with cls._singleton_lock:
            cls._instance = None

    def __init__(
        self,
        checkpoint_store: Any | None = None,
        runner: Any | None = None,
        runner_callable: Callable[..., Any] | None = None,
        artifact_store: Any | None = None,
        policy_evaluator: Any | None = None,
        signing_backend: Any | None = None,
        config_resolver: Any | None = None,
        run_store: Any | None = None,
    ):
        self._active_runs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancellation_events: dict[str, threading.Event] = {}
        self._checkpoint_store = checkpoint_store
        self._runner = runner
        self._runner_callable = runner_callable
        self._artifact_store = artifact_store
        self._policy_evaluator = policy_evaluator
        self._signing_backend = signing_backend
        self._config_resolver = config_resolver
        self._run_store = run_store
        self._lock = threading.Lock()

    def set_dependency_graph(
        self,
        runner: Any | None = None,
        runner_callable: Callable[..., Any] | None = None,
        checkpoint_store: Any | None = None,
        artifact_store: Any | None = None,
        policy_evaluator: Any | None = None,
        signing_backend: Any | None = None,
        config_resolver: Any | None = None,
        run_store: Any | None = None,
    ) -> None:
        """Sets or updates the injected runtime dependency graph."""
        with self._lock:
            if runner is not None:
                self._runner = runner
            if runner_callable is not None:
                self._runner_callable = runner_callable
            if checkpoint_store is not None:
                self._checkpoint_store = checkpoint_store
            if artifact_store is not None:
                self._artifact_store = artifact_store
            if policy_evaluator is not None:
                self._policy_evaluator = policy_evaluator
            if signing_backend is not None:
                self._signing_backend = signing_backend
            if config_resolver is not None:
                self._config_resolver = config_resolver
            if run_store is not None:
                self._run_store = run_store

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
        import eval_runner.runner as runner_module

        cancel_ev = cancellation_event or threading.Event()
        with self._lock:
            existing_token = (
                self._active_runs.get(run_id, {}).get("resumption_token")
                if run_id in self._active_runs
                else None
            )
            effective_token = kwargs.pop("resumption_token", None) or existing_token
            self._cancellation_events[run_id] = cancel_ev
            self._active_runs[run_id] = {
                "status": "RUNNING",
                "scenario": scenario_data.get("metadata", {}).get("name", run_id),
                "scenario_data": scenario_data,
                "kwargs": kwargs,
                "resumption_checkpoint": resumption_checkpoint,
                "resumption_token": effective_token,
            }

        def _execute():
            try:
                if self._runner_callable:
                    results = self._runner_callable(
                        scenario_data,
                        run_id=run_id,
                        cancellation_event=cancel_ev,
                        resumption_checkpoint=resumption_checkpoint,
                        **kwargs,
                    )
                elif self._runner:
                    results = runner_module.run_scenario(
                        scenario_data,
                        run_id=run_id,
                        cancellation_event=cancel_ev,
                        resumption_checkpoint=resumption_checkpoint,
                        runner=self._runner,
                        **kwargs,
                    )
                else:
                    results = runner_module.run_scenario(
                        scenario_data,
                        run_id=run_id,
                        cancellation_event=cancel_ev,
                        resumption_checkpoint=resumption_checkpoint,
                        artifact_store=self._artifact_store,
                        checkpoint_store=self._checkpoint_store,
                        policy_evaluator=self._policy_evaluator,
                        signing_backend=self._signing_backend,
                        config_resolver=self._config_resolver,
                        run_store=self._run_store,
                        execution_backend=self,
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

    def resume(
        self,
        run_id: str,
        resumption_token: str | None = None,
        force_recovery: bool = False,
        **kwargs: Any,
    ) -> Any:
        """
        Resumes a paused evaluation run using session state and resumption token.
        Enforces strict execution state machine guards to prevent duplicate execution threads.
        """
        checkpoint = self.checkpoint_store.load(run_id)
        if not checkpoint and run_id in self._active_runs:
            checkpoint = self._active_runs[run_id].get("resumption_checkpoint")

        with self._lock:
            current_entry = self._active_runs.get(run_id)
            current_status = current_entry.get("status") if current_entry else None

            # Execution State Machine Guard
            if not force_recovery:
                # 1. Reject active running executions
                if current_status == "RUNNING":
                    raise RuntimeError(
                        f"Cannot resume run '{run_id}': run is currently in RUNNING state."
                    )

                # 2. Reject terminal execution states
                if current_status in ("COMPLETED", "FAILED", "ABORTED", "CANCELLED"):
                    raise RuntimeError(
                        f"Cannot resume run '{run_id}': reached terminal state '{current_status}'."
                    )

                # 3. If run was in active_runs and status is not WAITING_FOR_APPROVAL/PAUSED/UNKNOWN
                if current_status and current_status not in (
                    "WAITING_FOR_APPROVAL",
                    "AWAITING_APPROVAL",
                    "PAUSED",
                    "UNKNOWN",
                ):
                    raise RuntimeError(
                        f"Cannot resume run '{run_id}': invalid state '{current_status}'."
                    )

            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = "RUNNING"
                self._active_runs[run_id]["resumption_token"] = resumption_token
                if not checkpoint and not kwargs.get("force_submit", False):
                    return self._active_runs[run_id]

        scenario_data = (checkpoint.get("scenario_data") if checkpoint else None) or (
            self._active_runs.get(run_id, {}).get("scenario_data")
            if run_id in self._active_runs
            else None
        )
        if not scenario_data:
            raise RuntimeError(
                f"Cannot resume run '{run_id}': checkpoint does not contain required "
                "scenario state (fail-closed)."
            )

        background = kwargs.pop("background", False)
        return self.submit(
            run_id=run_id,
            scenario_data=scenario_data,
            background=background,
            resumption_checkpoint=checkpoint,
            resumption_token=resumption_token,
            **kwargs,
        )


__all__ = ["InProcessExecutionBackend"]
