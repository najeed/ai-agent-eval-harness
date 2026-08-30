"""
flight_recorder.py

A built-in plugin that subscribes to EventEmitter to record run traces.
This decouples logging from the core engine loop.
"""

import hashlib
import json
import logging
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval_runner.interfaces.artifact import ArtifactStore
from eval_runner.interfaces.signing import SigningBackend
from eval_runner.reference.local_artifact import LocalFileArtifactStore
from eval_runner.reference.signing import (
    LocalEd25519SigningBackend,
    NullSigningBackend,
    PQCSigningBackend,
)

from .events import CoreEvents, Event
from .plugins import BaseEvalPlugin
from .utils import rmtree_resilient

logger = logging.getLogger(__name__)


class FlightRecorderPlugin(BaseEvalPlugin):
    """Subscribes to all core events and writes them to run.jsonl files."""

    _subscribed = False

    def __init__(
        self,
        signing_backend: SigningBackend | None = None,
        artifact_store: ArtifactStore | None = None,
        log_dir: Path | str | None = None,
    ):
        import eval_runner.config as config

        self.log_dir = (
            Path(log_dir)
            if log_dir is not None
            else Path(os.getenv("RUN_LOG_DIR", str(config.RUN_LOG_DIR)))
        )
        self.per_run = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
        self.master = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"

        self._enforce_safety_floor()

        self.master_log_path = self.log_dir / "run.jsonl"
        self.log_rotate_count = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))

        # State-aware handles for Windows stability
        self._handles = {}
        self._lock = threading.Lock()

        # [Iteration 4: Compliance DNA]
        self._sequence_numbers = {}  # Per-run sequence counters
        self._private_key_path = os.getenv("EVAL_SIGNING_KEY")
        self._audit_level = int(os.getenv("AUDIT_LEVEL", "2"))

        # Interface Wiring: ArtifactStore & SigningBackend
        self.artifact_store = artifact_store or LocalFileArtifactStore(base_dir=self.log_dir)

        if signing_backend is not None:
            self.signing_backend = signing_backend
        elif self._private_key_path:
            self.signing_backend = LocalEd25519SigningBackend()
        else:
            self.signing_backend = NullSigningBackend()

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

    def _enforce_safety_floor(self):
        """
        [Forensic Safety Floor] (AgentV v1.6.0)
        Prevents "Black Hole" configurations where no telemetry is recorded.
        If both logging paths are disabled, forces Vaulted isolation.
        """
        if not self.per_run and not self.master:
            sys.stderr.write(
                "⚠️  [FlightRecorder] [WARNING] Industrial Safety Override: Zero-Logging detected.\n"
            )
            sys.stderr.write(
                "⚠️  [FlightRecorder] Reclaiming Isolated Vault "
                "(RUN_LOG_PER_RUN=true) for compliance.\n"
            )
            self.per_run = True

    def handle_event(self, event: Event):
        """Callback for EventEmitter."""
        data = event.to_dict()
        run_id = (
            data.get("run_id")
            or (data.get("data", {}).get("run_id") if isinstance(data.get("data"), dict) else None)
            or "unknown"
        )

        # [Iteration 4: Compliance DNA]
        with self._lock:
            if run_id not in self._sequence_numbers:
                self._sequence_numbers[run_id] = 0
            self._sequence_numbers[run_id] += 1
            data["_seq"] = self._sequence_numbers[run_id]
            data["_ts_iso"] = datetime.now().astimezone().isoformat()

        # Special handling for RUN_START to initialize environment
        if event.name == CoreEvents.RUN_START:
            with self._lock:
                # [Refresher] Re-read environment variables for dynamic runtime configuration
                import eval_runner.config as config

                self.log_dir = Path(os.getenv("RUN_LOG_DIR", str(config.RUN_LOG_DIR)))
                self.per_run = os.getenv("RUN_LOG_PER_RUN", "true").lower() == "true"
                self.master = os.getenv("RUN_LOG_MASTER", "true").lower() == "true"

                self._enforce_safety_floor()

                self.log_rotate_count = int(os.getenv("RUN_LOG_ROTATE_COUNT", "0"))
                self.master_log_path = self.log_dir / "run.jsonl"

            if self.log_rotate_count > 0:
                self.rotate_logs(is_new_run=True)

        # Resolve paths dynamically to support parallel runs in the same process
        per_run_log_path = None
        if self.per_run and run_id != "unknown":
            run_vault_dir = self.log_dir / run_id
            per_run_log_path = run_vault_dir / "run.jsonl"

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
        backend_can_sign = not isinstance(self.signing_backend, NullSigningBackend) and (
            self._private_key_path is not None
            or getattr(self.signing_backend, "is_remote", False)
            or hasattr(self.signing_backend, "can_sign")
            or isinstance(self.signing_backend, PQCSigningBackend)
        )
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

        # Serialize and write
        content = json.dumps(data) + "\n"

        def _write_buffered(path, content):
            # [WinHardening] Persistent handles with thread safety
            path_str = str(path)
            with self._lock:
                if path_str not in self._handles:
                    # Ensure parent directory exists (Defensive for industrial stability)
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    self._handles[path_str] = open(path, "a", encoding="utf-8", buffering=1)
                self._handles[path_str].write(content)

        try:
            if per_run_log_path:
                if run_id and run_id != "unknown" and self.artifact_store:
                    self.artifact_store.store_artifact(
                        run_id=run_id,
                        artifact_name="run.jsonl",
                        content=content,
                        content_type="application/x-ndjson",
                        metadata={"event": data.get("event"), "seq": data.get("seq")},
                        append=True,
                    )
                else:
                    _write_buffered(per_run_log_path, content)

            if self.master:
                _write_buffered(self.master_log_path, content)
        except Exception as e:
            sys.stderr.write(f"   [FlightRecorder] [ERROR] File I/O Error: {e}\n")
            if os.getenv("EVAL_PERSISTENCE_FAIL_CLOSED", "false").lower() == "true":
                raise RuntimeError(
                    f"TracePersistenceError: Failed to persist telemetry "
                    f"event for run '{run_id}': {e}"
                ) from e

    def finalize_run(self, run_id: str | None = None):
        """
        Explicitly closes file handles and flushes telemetry to disk.
        Critical for resolving Windows file-lock races.
        If run_id is provided, only closes handles associated with that run.
        """
        with self._lock:
            # Determine which handles to close
            if run_id and run_id != "unknown":
                # Find handles associated with this run
                run_vault_dir = self.log_dir / run_id
                target_path = str(run_vault_dir / "run.jsonl")
                paths_to_close = [target_path] if target_path in self._handles else []
            else:
                # Close ALL handles (Legacy/Global cleanup)
                paths_to_close = list(self._handles.keys())

            for path_str in paths_to_close:
                handle = self._handles.pop(path_str, None)
                if not handle:
                    continue
                try:
                    handle.flush()
                    # [Staff Note] Force physical sync to prevent metadata corruption on crash
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

        if run_id and run_id != "unknown" and self.artifact_store:
            try:
                trace_content = ""
                try:
                    raw_art = self.artifact_store.get_artifact(run_id, "run.jsonl")
                    if raw_art:
                        trace_content = (
                            raw_art.decode("utf-8") if isinstance(raw_art, bytes) else str(raw_art)
                        )
                except Exception as art_err:
                    logger.debug(f"Artifact store get trace notice: {art_err}")

                if not trace_content:
                    run_vault_dir = self.log_dir / run_id
                    target_path = run_vault_dir / "run.jsonl"
                    if target_path.exists():
                        trace_content = target_path.read_text(encoding="utf-8")

                trace_bytes = (
                    trace_content.encode("utf-8")
                    if isinstance(trace_content, str)
                    else bytes(trace_content)
                )
                trace_digest = f"sha3_256:{hashlib.sha3_256(trace_bytes).hexdigest()}"
                line_count = (
                    len([line for line in trace_content.strip().split("\n") if line.strip()])
                    if trace_content
                    else 0
                )

                seal_payload = {
                    "status": "finalized",
                    "run_id": run_id,
                    "trace_digest": trace_digest,
                    "event_count": line_count,
                    "sealed_at": datetime.now(UTC).isoformat(),
                    "algorithm": "sha3_256",
                }

                try:
                    from eval_runner.identity import get_default_signer

                    signer = get_default_signer()
                    if signer:
                        seal_bytes = json.dumps(
                            seal_payload, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                        seal_payload["signature"] = signer.sign(seal_bytes).hex()
                        seal_payload["signer_identity"] = getattr(signer, "identity", "local-node")
                except Exception as sign_e:
                    logger.debug(f"Trace seal signing notice: {sign_e}")

                self.artifact_store.store_artifact(
                    run_id=run_id,
                    artifact_name="trace_seal.json",
                    content=json.dumps(seal_payload, indent=2),
                    content_type="application/json",
                    overwrite=True,
                )
            except Exception as e:
                logger.debug(f"Artifact store finalize seal error: {e}")

        # Cleanup sequence number if finalizing a specific run
        if run_id:
            self._sequence_numbers.pop(run_id, None)

    def after_evaluation(
        self, context: Any, results: list, span_context: dict[str, Any] | None = None
    ):
        """
        Core Hook: Lifecycle aware finalization.
        This is called by the engine before the evaluator returns control.
        """
        self.finalize_run(run_id=getattr(context, "run_id", None))

    def rotate_logs(self, is_new_run: bool = False):
        """
        Industrial-Grade Vault Rotation.
        Keeps only the latest N run subdirectories (vaults) based on disk state.
        This ignores root-level flat files, enforcing the vaulted methodology.
        """
        try:
            # 1. Collect only Vault Directories
            vaults = [d for d in self.log_dir.iterdir() if d.is_dir()]

            # 2. Sort by modification time (Latest first)
            targets = sorted(vaults, key=lambda x: x.stat().st_mtime, reverse=True)

            # [Retention Policy Enforcement]
            # If we are starting a new run, we keep N-1 existing runs to make room.
            effective_count = self.log_rotate_count
            if is_new_run:
                effective_count = max(0, self.log_rotate_count - 1)

            if len(targets) > effective_count:
                for old_vault in targets[effective_count:]:
                    try:
                        # Industrial-grade resilient purge of the entire vault directory
                        rmtree_resilient(old_vault)
                    except Exception as e:
                        sys.stderr.write(
                            "[FlightRecorder] [WARNING] Error rotating log vault "
                            f"{old_vault.name}: {e}\n"
                        )
        except Exception as e:
            # Robust defensive catch for IO/Permission errors during scan
            sys.stderr.write(
                f"   [FlightRecorder] [ERROR] Scan failure during vault rotation: {e}\n"
            )

    def flush(self):
        """Explicit flush trigger."""
        with self._lock:
            for handle in self._handles.values():
                try:
                    handle.flush()
                    os.fsync(handle.fileno())
                except Exception as e:
                    sys.stderr.write(f"   [FlightRecorder] [WARNING] Flush error: {e}\n")

    # Note: methods like before_evaluation are still available if needed
    # but handle_event covers most needs for the Flight Recorder.
