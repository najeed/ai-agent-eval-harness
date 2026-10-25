"""Provider-owned fenced certification lease."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class PerRunCertificationLock:
    """Cross-process certification lease delegated to the run provider.

    Local providers may use files internally; remote/database providers map the
    same owner/fencing contract to a transactional row or distributed lease.
    """

    _meta_lock: ClassVar[threading.Lock] = threading.Lock()
    _thread_locks: ClassVar[dict[str, threading.RLock]] = {}
    _depth: ClassVar[dict[tuple[str, int], int]] = {}
    _active_locks: ClassVar[set[str]] = set()

    def __init__(
        self,
        run_id: str,
        timeout_seconds: float = 10.0,
        *,
        run_store: Any,
        context: dict[str, Any] | None = None,
    ) -> None:
        if run_store is None:
            raise ValueError("RunStorageProvider is required for certification locking.")
        self.run_id, self.timeout_seconds, self.run_store, self.context = (
            run_id,
            timeout_seconds,
            run_store,
            context,
        )
        self.owner_id = f"pid_{os.getpid()}_th_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
        self.fencing_token = f"fence_{time.time_ns()}_{uuid.uuid4().hex[:8]}"
        with self._meta_lock:
            self._thread_lock = self._thread_locks.setdefault(run_id, threading.RLock())
        self._acquired = False
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._lease_failure: RuntimeError | None = None
        self._lease_operation_lock = threading.Lock()

    @classmethod
    def is_locked(
        cls, run_id: str, *, run_store: Any | None = None, context: dict[str, Any] | None = None
    ) -> bool:
        if not run_id:
            return False
        with cls._meta_lock:
            if run_id in cls._active_locks:
                return True
        return bool(run_store and run_store.is_certification_leased(run_id, context=context))

    def verify_active(self) -> None:
        if self._lease_failure is not None:
            raise self._lease_failure
        if (
            not self._acquired
            or not self._renew_lease()
            or not self.run_store.verify_certification_lease(
                self.run_id,
                owner_id=self.owner_id,
                fencing_token=self.fencing_token,
                context=self.context,
            )
        ):
            raise RuntimeError(
                f"CertificationLockStolen: Lock for run '{self.run_id}' is not owned"
            )

    def _renew_lease(self) -> bool:
        """Serialize renewal calls with the heartbeat for file-backed providers."""
        with self._lease_operation_lock:
            return bool(
                self.run_store.renew_certification_lease(
                    self.run_id,
                    owner_id=self.owner_id,
                    fencing_token=self.fencing_token,
                    timeout_seconds=self.timeout_seconds,
                    context=self.context,
                )
            )

    def _renewal_interval(self) -> float:
        """Renew well before expiry without imposing a provider-specific TTL."""
        return max(0.25, min(20.0, self.timeout_seconds / 3.0))

    def _heartbeat(self) -> None:
        while not self._heartbeat_stop.wait(self._renewal_interval()):
            try:
                renewed = self._renew_lease()
            except Exception as exc:  # provider failures must fail certification closed
                self._lease_failure = RuntimeError(
                    f"CertificationLeaseRenewalFailed: {self.run_id}"
                )
                self._lease_failure.__cause__ = exc
                return
            if not renewed:
                self._lease_failure = RuntimeError(
                    f"CertificationLockStolen: Lock for run '{self.run_id}' is not owned"
                )
                return

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop.clear()
        self._lease_failure = None
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat,
            name=f"certification-lease-{self.run_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=max(1.0, self._renewal_interval() * 2))
        self._heartbeat_thread = None

    def acquire(self) -> None:
        key = (self.owner_id, threading.get_ident())
        with self._meta_lock:
            if self._depth.get(key, 0):
                self._depth[key] += 1
                self._acquired = True
                return
        if not self._thread_lock.acquire(timeout=self.timeout_seconds):
            raise TimeoutError(f"CertificationLockConflict: could not lock '{self.run_id}'")
        lease_acquired = False
        registered = False
        try:
            if not self.run_store.acquire_certification_lease(
                self.run_id,
                owner_id=self.owner_id,
                fencing_token=self.fencing_token,
                timeout_seconds=self.timeout_seconds,
                context=self.context,
            ):
                raise TimeoutError(f"CertificationLockConflict: could not lease '{self.run_id}'")
            lease_acquired = True
            from eval_runner.run_lifecycle import RunLifecycleState, transition_run_lifecycle

            transition_run_lifecycle(
                self.run_id,
                RunLifecycleState.FINALIZING,
                metadata={"fencing_token": self.fencing_token, "owner_id": self.owner_id},
                run_store=self.run_store,
                context=self.context,
            )
            with self._meta_lock:
                self._depth[key] = 1
                self._active_locks.add(self.run_id)
            registered = True
            self._acquired = True
            self._start_heartbeat()
        except Exception:
            self._stop_heartbeat()
            if registered:
                with self._meta_lock:
                    self._depth.pop(key, None)
                    self._active_locks.discard(self.run_id)
            self._acquired = False
            if lease_acquired:
                try:
                    self.run_store.release_certification_lease(
                        self.run_id,
                        owner_id=self.owner_id,
                        fencing_token=self.fencing_token,
                        context=self.context,
                    )
                except Exception as lease_err:
                    logger.debug("Failed to release certification lease on abort: %s", lease_err)
            self._thread_lock.release()
            raise

    def release(self) -> None:
        key = (self.owner_id, threading.get_ident())
        with self._meta_lock:
            depth = self._depth.get(key, 0)
            if depth > 1:
                self._depth[key] = depth - 1
                return
            self._depth.pop(key, None)
        if not self._acquired:
            return
        try:
            self._stop_heartbeat()
            self.run_store.release_certification_lease(
                self.run_id,
                owner_id=self.owner_id,
                fencing_token=self.fencing_token,
                context=self.context,
            )
        finally:
            with self._meta_lock:
                self._active_locks.discard(self.run_id)
            self._acquired = False
            self._thread_lock.release()

    def __enter__(self) -> PerRunCertificationLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


__all__ = ["PerRunCertificationLock"]
