"""
eval_runner.reference.inprocess_backend
OSS Reference Implementation: InProcessExecutionBackend (v2.0.0).

Executes evaluation runs within the current process with thread isolation,
strict execution state machine enforcement, and full dependency graph injection.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from collections.abc import Callable
from typing import Any

from eval_runner.interfaces.backend import ExecutionBackend
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore
from eval_runner.run_lifecycle import (
    RunLifecycleState,
    RunSuspendedForApproval,
    transition_run_lifecycle,
)

logger = logging.getLogger(__name__)


def get_execution_backend() -> InProcessExecutionBackend:
    """Canonical factory to resolve the active execution backend."""
    return InProcessExecutionBackend.get_instance()


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
            from agentv_runtime.discovery import set_extension

            set_extension("execution_backends", cls._instance)
            return cls._instance

    @classmethod
    def clear_instance(cls) -> None:
        """Resets singleton instance for test isolation."""
        from agentv_runtime.discovery import reset_extensions

        reset_extensions("execution_backends")
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
        # Provider ownership is per execution, not per backend singleton.  A
        # backend can outlive multiple runs and must not re-resolve a global
        # provider while resuming one that was submitted under another scope.
        self._run_providers: dict[str, tuple[Any, dict[str, Any] | None]] = {}
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

    @staticmethod
    def _terminal_status(results: Any, cancelled: bool) -> str:
        """Map the runner's authoritative outcome to a durable run status."""
        if cancelled:
            return "ABORTED"

        metadata = getattr(results, "metadata", None)
        if isinstance(metadata, dict):
            outcome = str(metadata.get("outcome") or "").lower()
            if outcome == "pass":
                return "COMPLETED"
            if outcome in {"fail", "failure", "evaluation_invalid"}:
                return "FAILED"

        if isinstance(results, dict):
            status = str(results.get("status") or "").upper()
            if status in {"FAILED", "FAILURE", "VERIFICATION_FAILED", "CERTIFICATION_FAILED"}:
                return "FAILED"
            if results.get("passed") is False:
                return "FAILED"

        successful = getattr(results, "successful_attempts", None)
        total = getattr(results, "total_attempts", None)
        if isinstance(successful, int) and isinstance(total, int) and total > 0:
            return "COMPLETED" if successful == total else "FAILED"
        return "COMPLETED"

    def _update_durable_status(self, run_id: str, status: str) -> None:
        """Keep the injected RunStore's projection aligned with backend completion."""
        with self._lock:
            provider, context = self._run_providers.get(run_id, (self._run_store, None))
        if provider is None or not hasattr(provider, "update_run_status"):
            return
        try:
            if not provider.update_run_status(run_id, status, context=context):
                logger.warning("RunStore rejected terminal status %s for run %s", status, run_id)
        except Exception as store_err:
            logger.warning(
                "Failed persisting terminal status %s for run %s: %s",
                status,
                run_id,
                store_err,
            )

    @property
    def checkpoint_store(self):
        if self._checkpoint_store is None:
            from agentv_runtime.discovery import resolve_extension

            self._checkpoint_store = resolve_extension(
                "checkpoint_stores",
                default_factory=SQLiteCheckpointStore,
            )
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
        requested_run_store = kwargs.pop("run_store", None)
        metadata = kwargs.get("metadata") or {}
        requested_context = kwargs.pop("context", None) or metadata.get("runtime_context")
        with self._lock:
            existing_provider = self._run_providers.get(run_id)
            run_store = requested_run_store or (existing_provider[0] if existing_provider else None)
            if run_store is None:
                run_store = self._run_store
            if run_store is None:
                # This is the ownership boundary for an unconfigured backend.
                # Never repeat this lookup from resume/finalization paths.
                from eval_runner.storage_resolver import resolve_run_storage_provider

                run_store = resolve_run_storage_provider()
            if existing_provider is not None and existing_provider[0] is not run_store:
                raise RuntimeError(f"RunStorageProviderAffinityViolation: {run_id}")
            context = dict(existing_provider[1] or {}) if existing_provider else {}
            if requested_context:
                context.update(requested_context)
            self._run_providers[run_id] = (run_store, context or None)
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

        # Wire dependency graph into self._runner if runner instance provided
        if self._runner and hasattr(self._runner, "set_dependency_graph"):
            self._runner.set_dependency_graph(
                artifact_store=self._artifact_store,
                checkpoint_store=self._checkpoint_store,
                policy_evaluator=self._policy_evaluator,
                signing_backend=self._signing_backend,
                config_resolver=self._config_resolver,
                run_store=run_store,
            )

        def _execute():
            try:
                if self._runner_callable:
                    # Provide injected dependency graph as kwargs to custom callable
                    results = self._runner_callable(
                        scenario_data,
                        run_id=run_id,
                        cancellation_event=cancel_ev,
                        resumption_checkpoint=resumption_checkpoint,
                        resumption_token=effective_token,
                        artifact_store=self._artifact_store,
                        checkpoint_store=self._checkpoint_store,
                        policy_evaluator=self._policy_evaluator,
                        signing_backend=self._signing_backend,
                        config_resolver=self._config_resolver,
                        run_store=run_store,
                        execution_backend=self,
                        **kwargs,
                    )
                elif self._runner:
                    results = runner_module.run_scenario(
                        scenario_data,
                        run_id=run_id,
                        cancellation_event=cancel_ev,
                        resumption_checkpoint=resumption_checkpoint,
                        resumption_token=effective_token,
                        runner=self._runner,
                        artifact_store=self._artifact_store,
                        checkpoint_store=self._checkpoint_store,
                        policy_evaluator=self._policy_evaluator,
                        signing_backend=self._signing_backend,
                        config_resolver=self._config_resolver,
                        run_store=run_store,
                        execution_backend=self,
                        **kwargs,
                    )
                else:
                    results = runner_module.run_scenario(
                        scenario_data,
                        run_id=run_id,
                        cancellation_event=cancel_ev,
                        resumption_checkpoint=resumption_checkpoint,
                        resumption_token=effective_token,
                        artifact_store=self._artifact_store,
                        checkpoint_store=self._checkpoint_store,
                        policy_evaluator=self._policy_evaluator,
                        signing_backend=self._signing_backend,
                        config_resolver=self._config_resolver,
                        run_store=run_store,
                        execution_backend=self,
                        **kwargs,
                    )

                terminal_status = self._terminal_status(results, cancel_ev.is_set())
                with self._lock:
                    if run_id in self._active_runs:
                        self._active_runs[run_id]["status"] = terminal_status
                        self._active_runs[run_id]["results"] = results
                self._update_durable_status(run_id, terminal_status)
                try:
                    submission = run_store.get_submission(run_id, context=context or None)
                    if submission:
                        run_store.transition_submission(
                            run_id,
                            ("RUNNING", "DISPATCHED"),
                            terminal_status,
                            context=submission["context"],
                        )
                except Exception as admission_err:
                    logger.debug(
                        "Failed updating provider submission on completion: %s", admission_err
                    )
                return results
            except RunSuspendedForApproval as susp:
                logger.info("Run %s entered durable suspension: %s", run_id, susp)
                with self._lock:
                    if run_id in self._active_runs:
                        self._active_runs[run_id]["status"] = "PAUSED_FOR_APPROVAL"
                        self._active_runs[run_id]["approval_token"] = susp.approval_token
                        self._active_runs[run_id]["checkpoint_id"] = susp.checkpoint_id
                        self._active_runs[run_id]["resumption_checkpoint"] = susp.checkpoint
                try:
                    submission = run_store.get_submission(run_id, context=context or None)
                    if submission:
                        run_store.transition_submission(
                            run_id,
                            "RUNNING",
                            "PAUSED_FOR_APPROVAL",
                            context=submission["context"],
                        )
                except Exception as admission_err:
                    logger.debug(
                        "Failed updating provider submission on suspension: %s", admission_err
                    )
                return {
                    "status": "PAUSED_FOR_APPROVAL",
                    "run_id": run_id,
                    "approval_token": susp.approval_token,
                    "checkpoint_id": susp.checkpoint_id,
                }
            except Exception as e:
                logger.error("Execution failed for run %s: %s", run_id, e, exc_info=True)
                with self._lock:
                    if run_id in self._active_runs:
                        self._active_runs[run_id]["status"] = "FAILED"
                        self._active_runs[run_id]["error"] = str(e)
                self._update_durable_status(run_id, "FAILED")
                try:
                    submission = run_store.get_submission(run_id, context=context or None)
                    if submission:
                        run_store.transition_submission(
                            run_id,
                            ("RUNNING", "DISPATCHED", "PAUSED_FOR_APPROVAL"),
                            "FAILED",
                            context=submission["context"],
                        )
                    existing_manifest = run_store.get_manifest(run_id, context=context or None)
                    if not existing_manifest:
                        failed_manifest = {
                            "run_id": run_id,
                            "scenario_id": str(
                                scenario_data.get("id")
                                or scenario_data.get("metadata", {}).get("name")
                                or run_id
                            ),
                            "status": "FAILED",
                            "error": str(e),
                            "attempts": kwargs.get("attempts", 1),
                            "pass_at_k": 0.0,
                            "results": [],
                            "context": context or (submission or {}).get("context", {}),
                        }
                        if hasattr(run_store, "save_run_manifest"):
                            run_store.save_run_manifest(
                                run_id, failed_manifest, context=context or None
                            )
                except Exception as save_err:
                    logger.debug("Failed saving failed manifest in inprocess_backend: %s", save_err)
                if not background:
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
            if run_id in self._active_runs:
                return self._active_runs[run_id]
        # Check durable store on cold read
        cp = self.checkpoint_store.load(run_id)
        if cp:
            return {
                "status": cp.get("status")
                or (cp.get("session_state") or {}).get("status", "PAUSED"),
                "run_id": run_id,
                "checkpoint": cp,
            }
        return {"status": "UNKNOWN"}

    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        with self._lock:
            if run_id in self._cancellation_events:
                self._cancellation_events[run_id].set()
            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = "ABORTED"
                self._active_runs[run_id]["cancel_reason"] = reason or "Cancelled by user"
                try:
                    run_store = self._run_store
                    submission = run_store.get_submission(run_id)
                    if submission:
                        run_store.transition_submission(
                            run_id,
                            ("RUNNING", "DISPATCHED", "PAUSED_FOR_APPROVAL"),
                            "ABORTED",
                            context=submission["context"],
                        )
                except Exception as admission_err:
                    logger.debug("Failed updating provider submission on cancel: %s", admission_err)
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
        Enforces strict execution state machine guards to prevent duplicate execution threads,
        validating durable checkpoint state across cold process restarts.
        """
        # A resumption token is also used by ordinary crash recovery.  It is
        # an approval credential only when the checkpoint is approval-gated;
        # treating every recovery token as an approval record broke non-HITL
        # lifecycle recovery and changed the state-machine error precedence.
        checkpoint = self.checkpoint_store.load(run_id)
        if not checkpoint and run_id in self._active_runs:
            checkpoint = self._active_runs[run_id].get("resumption_checkpoint")

        checkpoint_state = (checkpoint or {}).get("session_state") or (checkpoint or {})
        expected_token = checkpoint_state.get("approval_token")

        with self._lock:
            current_entry = self._active_runs.get(run_id)
            current_status = current_entry.get("status") if current_entry else None

            # If not in active_runs (cold process restart), check durable checkpoint status
            if current_status is None and checkpoint:
                current_status = checkpoint.get("status") or (
                    checkpoint.get("session_state") or {}
                ).get("status", "PAUSED")

            # Never mutate lifecycle state for a run whose execution contract
            # cannot be recovered. This preserves the fail-closed boundary for
            # unknown IDs before any durable write is attempted.
            if current_entry is None and not checkpoint:
                raise RuntimeError(
                    f"Cannot resume run '{run_id}': execution state is unavailable (fail-closed)."
                )

            approval_states = {"WAITING_FOR_APPROVAL", "AWAITING_APPROVAL", "PAUSED_FOR_APPROVAL"}
            if current_status in approval_states and not resumption_token:
                raise PermissionError(
                    f"Cannot resume run '{run_id}': approval-gated checkpoint requires a token."
                )

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

                # 3. Reject invalid intermediate execution states
                if current_status and current_status not in (*approval_states, "PAUSED", "UNKNOWN"):
                    raise RuntimeError(
                        f"Cannot resume run '{run_id}': invalid state '{current_status}'."
                    )

        requires_approval = bool(expected_token) or current_status in approval_states
        if requires_approval:
            if not resumption_token:
                raise PermissionError(
                    f"Cannot resume run '{run_id}': approval-gated checkpoint requires a token."
                )
            from eval_runner.runtime_services import resolve_approval_store

            approval = resolve_approval_store().get_request(resumption_token)
            if not approval or approval.run_id != run_id or approval.status != "APPROVED":
                raise PermissionError(
                    f"Cannot resume run '{run_id}': approval has not been authoritatively approved."
                )
            if approval.checkpoint_id:
                checkpoint_ref = str(approval.checkpoint_id)
                checkpoint_id = checkpoint_ref.rsplit("/", 1)[-1]
                checkpoint = self.checkpoint_store.load(run_id, checkpoint_id)
                if not checkpoint:
                    raise PermissionError(
                        f"Cannot resume run '{run_id}': approval checkpoint is unavailable."
                    )
                checkpoint_state = checkpoint.get("session_state") or checkpoint
                expected_token = checkpoint_state.get("approval_token")
            if not expected_token or not hmac.compare_digest(
                str(expected_token), str(resumption_token)
            ):
                raise PermissionError(
                    f"Cannot resume run '{run_id}': approval token does not bind to checkpoint."
                )
            action_payload = checkpoint_state.get("action_payload")
            if action_payload and approval.outbound_payload_hash:
                payload_hash = hashlib.sha3_256(
                    str(sorted(action_payload.items())).encode("utf-8")
                ).hexdigest()
                if not hmac.compare_digest(payload_hash, approval.outbound_payload_hash):
                    raise PermissionError(
                        f"Cannot resume run '{run_id}': approval payload binding is invalid."
                    )

        # Re-open the durable lifecycle before the background runner emits its
        # first event.  The approval gate deliberately closes trace writes;
        # changing only this backend's in-memory status leaves an enterprise
        # RunStore at PAUSED_FOR_APPROVAL and rejects every resumed event.
        # This is deliberately after approval validation, so an unapproved
        # token can never reopen a paused evidence stream.
        requested_run_store = kwargs.pop("run_store", None)
        requested_context = kwargs.get("context") or (kwargs.get("metadata") or {}).get(
            "runtime_context"
        )
        with self._lock:
            bound_provider = self._run_providers.get(run_id)
        provider = requested_run_store or (bound_provider[0] if bound_provider else self._run_store)
        if provider is None:
            raise RuntimeError(
                f"Cannot resume run '{run_id}': Provider ownership is unavailable (fail-closed)."
            )
        if bound_provider is not None and bound_provider[0] is not provider:
            raise RuntimeError(f"RunStorageProviderAffinityViolation: {run_id}")
        context = dict(bound_provider[1] or {}) if bound_provider else {}
        if requested_context:
            context.update(requested_context)
        with self._lock:
            self._run_providers[run_id] = (provider, context or None)

        if force_recovery:
            # Explicit recovery is the sole exception to the monotonic normal
            # lifecycle: a terminal record cannot be reopened through
            # ``transition_run_lifecycle`` because FAILED is intentionally
            # treated as invalid for ordinary trace writes.  Preserve the
            # backend contract's opt-in recovery semantics without weakening
            # the approval-gated path above.
            if not provider.update_run_status(
                run_id, RunLifecycleState.OPEN.value, context=context or None
            ):
                raise RuntimeError(f"RunStorageProvider rejected recovery for '{run_id}'.")
        else:
            transition_run_lifecycle(
                run_id, RunLifecycleState.OPEN, run_store=provider, context=context or None
            )

        with self._lock:
            if run_id in self._active_runs:
                self._active_runs[run_id]["status"] = "RUNNING"
                self._active_runs[run_id]["resumption_token"] = resumption_token
                if not checkpoint and not kwargs.get("force_submit", False):
                    return self._active_runs[run_id]

        provider_manifest = provider.get_manifest(run_id, context=context or None) or {}
        scenario_data = provider_manifest.get("scenario_data")

        if not scenario_data:
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

        # Preserve authoritative execution_mode across resumption
        resumed_metadata = dict(kwargs.get("metadata") or {})
        orig_mode = kwargs.pop("execution_mode", None)
        if not orig_mode:
            if checkpoint:
                chk_meta = (
                    checkpoint.get("metadata")
                    or (checkpoint.get("session_state") or {}).get("metadata")
                    or {}
                )
                orig_mode = chk_meta.get("execution_mode")
            if not orig_mode and run_id in self._active_runs:
                orig_mode = self._active_runs[run_id].get("kwargs", {}).get("execution_mode")
                if not orig_mode:
                    orig_meta = self._active_runs[run_id].get("kwargs", {}).get("metadata") or {}
                    orig_mode = orig_meta.get("execution_mode")
            if not orig_mode:
                execution_manifest = provider_manifest.get("execution_manifest") or {}
                runtime_config = execution_manifest.get("runtime_config")
                if isinstance(runtime_config, dict):
                    orig_mode = runtime_config.get("execution_mode")
        if orig_mode:
            resumed_metadata["execution_mode"] = orig_mode
            resumed_metadata["execution_mode_declared"] = True
            if isinstance(scenario_data, dict):
                scenario_data["execution_mode"] = orig_mode
        kwargs["metadata"] = resumed_metadata

        background = kwargs.pop("background", False)
        kwargs["run_store"] = provider
        if context:
            kwargs["context"] = context
        return self.submit(
            run_id=run_id,
            scenario_data=scenario_data,
            background=background,
            resumption_checkpoint=checkpoint,
            resumption_token=resumption_token,
            **kwargs,
        )


__all__ = ["InProcessExecutionBackend"]
