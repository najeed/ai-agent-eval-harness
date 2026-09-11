"""
eval_runner.certification_lock
Exclusive per-run certification lock spanning outcome extraction -> freeze -> sign -> seal.

Guarantees transactional mutual exclusion during certification:
1. Prevents concurrent trace appends/writes during certification.
2. Eliminates TOCTOU race conditions between outcome extraction and trace sealing.
3. Fails closed if another certification attempt is currently active on the run.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, ClassVar

from eval_runner import config

logger = logging.getLogger(__name__)


class PerRunCertificationLock:
    """
    Exclusive per-run certification lock.
    Thread-safe and process-safe lock using in-memory and filesystem markers.
    """

    _thread_locks: ClassVar[dict[str, threading.RLock]] = {}
    _meta_lock: ClassVar[threading.Lock] = threading.Lock()
    _active_locks: ClassVar[set[str]] = set()
    _thread_depth: ClassVar[dict[tuple[str, int], int]] = {}

    def __init__(self, run_id: str, timeout_seconds: float = 10.0) -> None:
        self.run_id = run_id
        self.timeout_seconds = timeout_seconds
        with self._meta_lock:
            if run_id not in self._thread_locks:
                self._thread_locks[run_id] = threading.RLock()
            self._thread_lock = self._thread_locks[run_id]
        self.lock_dir = config.RUN_LOG_DIR / run_id
        self.lock_file = self.lock_dir / ".certification.lock"
        self._acquired = False

    @classmethod
    def is_locked(cls, run_id: str) -> bool:
        """Checks if a run is currently locked for certification."""
        if not run_id:
            return False
        with cls._meta_lock:
            if run_id in cls._active_locks:
                return True
        lock_file = config.RUN_LOG_DIR / run_id / ".certification.lock"
        return lock_file.exists()

    def acquire(self) -> None:
        thread_id = threading.get_ident()
        key = (self.run_id, thread_id)
        with self._meta_lock:
            current_depth = self._thread_depth.get(key, 0)
            if current_depth > 0:
                self._thread_depth[key] = current_depth + 1
                self._acquired = True
                return

        start_time = time.monotonic()
        acquired_thread = self._thread_lock.acquire(timeout=self.timeout_seconds)
        if not acquired_thread:
            raise TimeoutError(
                f"CertificationLockConflict: could not acquire thread lock for run '{self.run_id}'"
            )

        try:
            self.lock_dir.mkdir(parents=True, exist_ok=True)
            while self.lock_file.exists():
                if time.monotonic() - start_time > self.timeout_seconds:
                    raise TimeoutError(
                        f"CertificationLockConflict: timed out waiting for run '{self.run_id}'"
                    )
                time.sleep(0.05)

            temp_lock = self.lock_dir / f".certification.lock.{os.getpid()}.tmp"
            temp_lock.write_text(
                f"pid={os.getpid()}\nts={time.time()}\nrun_id={self.run_id}\n",
                encoding="utf-8",
            )
            temp_lock.replace(self.lock_file)

            with self._meta_lock:
                self._active_locks.add(self.run_id)
                self._thread_depth[key] = 1
            self._acquired = True
        except Exception:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        thread_id = threading.get_ident()
        key = (self.run_id, thread_id)
        with self._meta_lock:
            current_depth = self._thread_depth.get(key, 0)
            if current_depth > 1:
                self._thread_depth[key] = current_depth - 1
                return
            self._thread_depth.pop(key, None)

        try:
            if self.lock_file.exists():
                try:
                    self.lock_file.unlink(missing_ok=True)
                except OSError as e:
                    logger.debug(
                        "Failed unlinking certification lock file for %s: %s", self.run_id, e
                    )
            with self._meta_lock:
                self._active_locks.discard(self.run_id)
        finally:
            if self._acquired:
                self._acquired = False
                self._thread_lock.release()

    def __enter__(self) -> PerRunCertificationLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
