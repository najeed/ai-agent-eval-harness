"""
flight_recorder.py

A built-in plugin that subscribes to EventEmitter to record run traces.
This decouples logging from the core engine loop.
"""

import json
import logging
import os
import sys
import threading
from datetime import datetime
from typing import Any

from eval_runner.interfaces.artifact import ArtifactStore
from eval_runner.interfaces.signing import SigningBackend
from eval_runner.runtime_services import (
    LocalEd25519SigningBackend,
    NullSigningBackend,
    resolve_artifact_store,
    resolve_signing_backend,
)

from .events import CoreEvents, Event
from .plugins import BaseEvalPlugin

logger = logging.getLogger(__name__)


class FlightRecorderPlugin(BaseEvalPlugin):
    """Subscribes to core events and appends them to the bound run provider."""

    _subscribed = False

    def __init__(
        self,
        signing_backend: SigningBackend | None = None,
        artifact_store: ArtifactStore | None = None,
        run_store: Any | None = None,
        log_dir: Any | None = None,
        certification_mode: bool = False,
    ):
        has_explicit_run_store = run_store is not None
        if run_store is None and log_dir is not None:
            from eval_runner.runtime_services import compose_local_run_store

            run_store = compose_local_run_store(log_dir)
        elif run_store is None:
            try:
                from eval_runner.runtime_services import resolve_run_store

                run_store = resolve_run_store()
            except Exception as exc:
                logger.debug("Failed resolving run store in init: %s", exc)
                run_store = None
        self._lock = threading.RLock()
        self._run_states: dict[str, str] = {}
        self._run_providers: dict[str, tuple[Any, dict[str, Any] | None]] = {}
        self._failed_runs: set[str] = set()
        self._certification_mode = certification_mode
        self._default_run_store = run_store
        self._has_explicit_default_run_store = has_explicit_run_store

        # [Iteration 4: Compliance DNA]
        self._sequence_numbers = {}  # Per-run sequence counters
        self._private_key_path = os.getenv("FLIGHT_RECORDER_KEY_PATH")
        self._audit_level = int(os.getenv("AUDIT_LEVEL", "2"))

        # Interface Wiring: ArtifactStore & SigningBackend
        if artifact_store is not None:
            self.artifact_store = resolve_artifact_store(explicit=artifact_store)
        elif log_dir is not None:
            from eval_runner.runtime_services import compose_local_artifact_store

            self.artifact_store = resolve_artifact_store(
                default_factory=lambda: compose_local_artifact_store(log_dir)
            )
        else:
            self.artifact_store = resolve_artifact_store()

        self.signing_backend = (
            resolve_signing_backend(explicit=signing_backend)
            if signing_backend is not None or os.getenv("AGENTV_SIGNING_BACKEND")
            else LocalEd25519SigningBackend()
            if self._private_key_path
            else NullSigningBackend()
        )

        # [Event Duplication Remediation]
        # Only subscribe to the global event bus once (Singleton Pattern)
        from . import events

        global_bus = events.EventEmitter.get_global()
        is_already_subbed = any(
            hasattr(sub, "__self__") and isinstance(sub.__self__, FlightRecorderPlugin)
            for sub in global_bus._subscribers
        )
        if not is_already_subbed:
            events.subscribe(self.handle_event)
            print("   [FlightRecorder] Registered singleton event listener.")

    def is_certification_mode(self, run_id: str | None = None) -> bool:
        """
        Determines whether the flight recorder is operating in certification/attestation mode.
        In this mode, telemetry persistence is intrinsically fail-closed.
        """
        return bool(
            self._certification_mode
            or os.getenv("AES_CERTIFICATION_MODE") == "1"
            or os.getenv("EVAL_CERTIFICATION_MODE", "").lower() in ("true", "1", "yes")
            or os.getenv("EVAL_ATTESTATION_MODE", "").lower() in ("true", "1", "yes")
        )

    def bind_run_provider(
        self, run_id: str, run_store: Any, context: dict[str, Any] | None = None
    ) -> None:
        if not run_id or run_id == "unknown" or run_store is None:
            return
        with self._lock:
            existing = self._run_providers.get(run_id)
            if existing is not None and existing[0] is not run_store:
                raise RuntimeError(f"RunStorageProviderAffinityViolation: {run_id}")
            existing_context = existing[1] if existing is not None else None
            merged_context = dict(existing_context or {})
            if context:
                merged_context.update(context)
            self._run_providers[run_id] = (run_store, merged_context or None)

    def release_run_provider(self, run_id: str) -> None:
        """Discard execution-scoped provider references after terminal sealing."""
        with self._lock:
            self._run_providers.pop(run_id, None)

    @classmethod
    def bind_active_recorder(
        cls, run_id: str, run_store: Any, context: dict[str, Any] | None = None
    ) -> None:
        from .events import EventEmitter

        for subscriber in EventEmitter.get_global()._subscribers:
            recorder = getattr(subscriber, "__self__", None)
            if isinstance(recorder, cls):
                recorder.bind_run_provider(run_id, run_store, context)

    @classmethod
    def release_active_recorder(cls, run_id: str, run_store: Any | None = None) -> None:
        """Release a terminal run's binding without disturbing another provider's run."""
        from .events import EventEmitter

        for subscriber in EventEmitter.get_global()._subscribers:
            recorder = getattr(subscriber, "__self__", None)
            if not isinstance(recorder, cls):
                continue
            # Certification may run in a different process from evaluation
            # (for example, a console worker after a restart).  There is then
            # no process-local binding to release; provider ownership has
            # already been enforced by the certification transaction.
            with recorder._lock:
                binding = recorder._run_providers.get(run_id)
            if binding is None:
                continue
            bound_store, _ = binding
            if run_store is None or bound_store is run_store:
                recorder.release_run_provider(run_id)

    def _provider_for_run(self, run_id: str) -> tuple[Any, dict[str, Any] | None]:
        with self._lock:
            bound = self._run_providers.get(run_id)
            if bound is not None:
                return bound
            if self._has_explicit_default_run_store and self._default_run_store is not None:
                return self._default_run_store, None
            default_run_store = self._default_run_store
        if default_run_store is None:
            try:
                from eval_runner.runtime_services import resolve_run_store

                default_run_store = resolve_run_store()
                with self._lock:
                    self._default_run_store = default_run_store
                    self._has_explicit_default_run_store = True
            except Exception:
                default_run_store = None
        if self._has_explicit_default_run_store and default_run_store is not None:
            return default_run_store, None
        raise RuntimeError(
            f"RunStorageProviderBindingRequired: recorder has no provider binding for '{run_id}'."
        )

    def handle_event(self, event: Event):
        """Callback for EventEmitter."""
        data = event.to_dict()
        run_id = (
            data.get("run_id")
            or (data.get("data", {}).get("run_id") if isinstance(data.get("data"), dict) else None)
            or "unknown"
        )

        # RUN_START must never reset an existing evidence vault.  A run id is a
        # single-use provenance identifier: any pre-existing vault or trace is a
        # collision, even if its lifecycle marker has not yet been written.
        if event.name == CoreEvents.RUN_START:
            with self._lock:
                if run_id and run_id != "unknown":
                    from eval_runner.run_lifecycle import (
                        RunLifecycleState,
                        get_run_lifecycle_state,
                    )

                    run_store, run_context = self._provider_for_run(run_id)
                    lifecycle_state = get_run_lifecycle_state(
                        run_id, run_store=run_store, context=run_context
                    )
                    is_resume = bool(data.get("is_resume"))
                    if not is_resume:
                        if lifecycle_state != RunLifecycleState.OPEN:
                            raise RuntimeError(
                                f"RunIdCollision: run '{run_id}' already has persistent "
                                "trace or lifecycle state; refusing to overwrite evidence."
                            )
                        self._run_states[run_id] = "RUNNING"
                        self._failed_runs.discard(run_id)
                        self._sequence_numbers[run_id] = 0
                    else:
                        if lifecycle_state in (
                            RunLifecycleState.FINALIZING,
                            RunLifecycleState.SEALED,
                            RunLifecycleState.INVALID,
                        ):
                            raise RuntimeError(
                                f"ResumptionError: run '{run_id}' is in state "
                                f"'{lifecycle_state.value}'; "
                                "refusing to append to finalized or invalid trace."
                            )
                        self._run_states[run_id] = "RUNNING"
                        self._failed_runs.discard(run_id)
                        # Provider events are the sole durable source when a
                        # process resumes.  Do not inspect a local trace.
                        initial_seq = max(
                            (
                                int(event.get("_seq", 0))
                                for event in run_store.get_events(
                                    run_id, offset=0, limit=10_000_000, context=run_context
                                )
                                if isinstance(event, dict)
                            ),
                            default=0,
                        )
                        self._sequence_numbers[run_id] = initial_seq

        with self._lock:
            run_state = self._run_states.get(run_id, "RUNNING")
            if run_state in ("FINALIZING", "SEALED"):
                logger.debug(
                    f"FlightRecorder write rejected: run '{run_id}' in state '{run_state}'"
                )
                return

        if run_id and run_id != "unknown":
            from eval_runner.run_lifecycle import assert_can_write_trace

            try:
                run_store, run_context = self._provider_for_run(run_id)
                assert_can_write_trace(run_id, run_store=run_store, context=run_context)
            except Exception as w_err:
                with self._lock:
                    self._run_states[run_id] = "CERTIFICATION_FAILED"
                    self._failed_runs.add(run_id)
                raise RuntimeError(
                    f"TracePersistenceError: Run '{run_id}' cannot accept trace writes: {w_err}"
                ) from w_err

        # [Iteration 4: Compliance DNA]
        with self._lock:
            if run_id not in self._sequence_numbers:
                initial_seq = 0
                if run_id and run_id != "unknown":
                    run_store, run_context = self._provider_for_run(run_id)
                    initial_seq = max(
                        (
                            int(event.get("_seq", 0))
                            for event in run_store.get_events(
                                run_id, offset=0, limit=10_000_000, context=run_context
                            )
                            if isinstance(event, dict)
                        ),
                        default=0,
                    )
                self._sequence_numbers[run_id] = initial_seq
            self._sequence_numbers[run_id] += 1
            data["_seq"] = self._sequence_numbers[run_id]
            data["_ts_iso"] = datetime.now().astimezone().isoformat()

        # [Fail-Closed on Absence]
        require_signing = os.getenv("EVAL_REQUIRE_SIGNING", "false").lower() == "true"
        if (
            require_signing
            and not self._private_key_path
            and isinstance(self.signing_backend, NullSigningBackend)
        ):
            err = (
                "CryptographicSigningError: Signing is mandatory (EVAL_REQUIRE_SIGNING=true), "
                "but no signing key or backend was provided."
            )
            sys.stderr.write(f"   [FlightRecorder] [ERROR] {err}\n")
            raise RuntimeError(err)

        # [Trace-level integrity (Fail-Closed Cryptography via SigningBackend)]
        backend_can_sign = getattr(self.signing_backend, "can_sign", lambda: False)()
        should_sign = (
            self._audit_level >= 2 and (self._private_key_path is not None or backend_can_sign)
        ) or backend_can_sign
        if should_sign:
            try:
                payload = json.dumps(data, sort_keys=True).encode("utf-8")
                key_id = self._private_key_path or getattr(
                    self.signing_backend, "key_id", "default"
                )
                data["_sig"] = self.signing_backend.sign_payload(payload, key_id)
            except Exception as e:
                data["_sig_error"] = str(e)
                msg = (
                    f"   [FlightRecorder] [ERROR] Cryptographic signing failed for "
                    f"run '{run_id}': {e}\n"
                )
                sys.stderr.write(msg)
                # Fail-closed under AUDIT_LEVEL >= 2
                if os.getenv("EVAL_SIGNING_FAIL_CLOSED", "true").lower() == "true":
                    err = (
                        "CryptographicSigningError: Failed to sign trace event at "
                        f"AUDIT_LEVEL={self._audit_level}: {e}"
                    )
                    raise RuntimeError(err) from e

        try:
            if not run_id or run_id == "unknown":
                raise RuntimeError("TracePersistenceError: trace event has no run ownership")
            run_store, run_context = self._provider_for_run(run_id)
            # Only the bound provider serializes canonical trace bytes.  The
            # recorder never maintains an alternate filesystem/master-log copy.
            run_store.append_events(run_id, [data], context=run_context)
        except Exception as e:
            sys.stderr.write(f"   [FlightRecorder] [ERROR] File I/O Error: {e}\n")
            with self._lock:
                if run_id and run_id != "unknown":
                    self._run_states[run_id] = "CERTIFICATION_FAILED"
                    self._failed_runs.add(run_id)
            # Losing forensic evidence invalidates the evaluation, regardless
            # of runtime mode.  Continuing would allow an apparently completed
            # run with an incomplete audit record.
            raise RuntimeError(
                f"TracePersistenceError: Failed to persist telemetry event for run '{run_id}': {e}"
            ) from e

    def finalize_run(self, run_id: str | None = None):
        """Close recorder writes without publishing a certificate seal.

        The provider-native certification transaction is the sole authority
        allowed to transition a certifiable run to ``SEALED``.  Recorder
        finalization can only place an open run in ``FINALIZING`` and retains
        its provider binding for certification.
        """
        if not run_id:
            return

        with self._lock:
            if (
                run_id in self._failed_runs
                or self._run_states.get(run_id) == "CERTIFICATION_FAILED"
            ):
                self._run_states[run_id] = "CERTIFICATION_FAILED"
                raise RuntimeError(
                    f"TracePersistenceError: Run '{run_id}' transitioned to "
                    "CERTIFICATION_FAILED due to telemetry persistence failure; "
                    "cannot produce trace seal, certificate, or verification package."
                )

        if self.is_certification_mode(run_id) and isinstance(
            self.signing_backend, NullSigningBackend
        ):
            raise RuntimeError("AES_CERTIFICATION_MODE=1 requires a non-null cryptographic signer")

        from eval_runner.run_lifecycle import (
            RunLifecycleState,
            get_run_lifecycle_state,
            transition_run_lifecycle,
        )

        run_store, context = self._provider_for_run(run_id)
        state = get_run_lifecycle_state(run_id, run_store=run_store, context=context)
        if state == RunLifecycleState.SEALED:
            with self._lock:
                self._run_states[run_id] = "SEALED"
            return
        if state in {RunLifecycleState.OPEN, RunLifecycleState.PAUSED_FOR_APPROVAL}:
            transition_run_lifecycle(
                run_id,
                RunLifecycleState.FINALIZING,
                run_store=run_store,
                context=context,
            )
        with self._lock:
            self._run_states[run_id] = "FINALIZING"

        if self.artifact_store and run_id and run_id != "unknown":
            try:
                import hashlib
                from datetime import UTC, datetime

                from agentv_runtime.canonical import canonical_json_encode

                trace_bytes = run_store.get_trace_bytes(run_id, context=context) or b""
                trace_digest = f"sha3_256:{hashlib.sha3_256(trace_bytes).hexdigest()}"
                line_count = len([line for line in trace_bytes.split(b"\n") if line.strip()])

                seal_envelope = {
                    "status": "finalized",
                    "run_id": run_id,
                    "trace_digest": trace_digest,
                    "event_count": line_count,
                    "sealed_at": datetime.now(UTC).isoformat(),
                    "algorithm": "sha3_256",
                }

                signer = self.signing_backend
                if signer and not isinstance(signer, NullSigningBackend):
                    signer_id = str(getattr(signer, "identity", None) or "local-node")
                    seal_envelope["signer_identity"] = signer_id
                    key_id_val = getattr(signer, "key_id", None)
                    if not key_id_val and hasattr(signer, "get_key_id"):
                        key_id_val = signer.get_key_id()
                    if key_id_val and isinstance(key_id_val, str):
                        seal_envelope["key_id"] = key_id_val

                    seal_bytes = canonical_json_encode(seal_envelope)
                    if hasattr(signer, "sign"):
                        raw_sig = signer.sign(seal_bytes)
                    else:
                        raw_sig = signer.sign_payload(seal_bytes)
                    seal_envelope["signature"] = (
                        raw_sig.hex() if isinstance(raw_sig, bytes) else str(raw_sig)
                    )

                self.artifact_store.store_artifact(
                    run_id=run_id,
                    artifact_name="trace_seal.json",
                    content=json.dumps(seal_envelope, indent=2),
                    content_type="application/json",
                    overwrite=True,
                )
            except Exception as e:
                logger.debug(f"Artifact store finalize seal error: {e}")
                if self.is_certification_mode(run_id):
                    with self._lock:
                        self._run_states[run_id] = "CERTIFICATION_FAILED"
                        self._failed_runs.add(run_id)
                    raise

    def freeze_run(self, run_id: str) -> None:
        """Explicitly freezes a run in preparation for verification/certification."""
        if not run_id or run_id == "unknown":
            return
        with self._lock:
            self._run_states[run_id] = "FINALIZING"
            try:
                from eval_runner.run_lifecycle import (
                    RunLifecycleState,
                    transition_run_lifecycle,
                )

                transition_run_lifecycle(
                    run_id,
                    RunLifecycleState.FINALIZING,
                    run_store=self._provider_for_run(run_id)[0],
                    context=self._provider_for_run(run_id)[1],
                )
            except Exception as lc_err:
                self._run_states[run_id] = "CERTIFICATION_FAILED"
                self._failed_runs.add(run_id)
                raise RuntimeError(
                    f"TracePersistenceError: failed to persist FINALIZING lifecycle "
                    f"transition for run '{run_id}': {lc_err}"
                ) from lc_err
        self.finalize_run(run_id=run_id)

    def close_execution_writes(self, run_id: str | None = None) -> None:
        """Compatibility hook; providers own stream flushing and durability."""
        return None

    def on_cleanup_runs(self) -> None:
        """Release recorder handles before a console cleanup deletes vaults."""
        self.close_execution_writes(None)

    def get_run_state(self, run_id: str) -> str:
        """Returns the current lifecycle state for run_id (RUNNING, FINALIZING, SEALED)."""
        with self._lock:
            return self._run_states.get(run_id, "RUNNING")

    def after_evaluation(
        self, context: Any, results: list, span_context: dict[str, Any] | None = None
    ):
        """
        Core Hook: close execution writes only.

        This hook is called by the evaluator.  It deliberately does not seal: the
        certification transaction is the sole lifecycle owner for final sealing.
        """
        self.close_execution_writes(run_id=getattr(context, "run_id", None))

    def rotate_logs(self, is_new_run: bool = False):
        """Deprecated: retention is a provider responsibility."""
        return None

    def flush(self):
        """Compatibility hook; providers own stream flushing and durability."""
        return None

    # Note: methods like before_evaluation are still available if needed
    # but handle_event covers most needs for the Flight Recorder.
