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
from pathlib import Path
from typing import Any, ClassVar

from eval_runner import config

logger = logging.getLogger(__name__)

LOCK_LEASE_SECONDS = 60.0


def _is_process_alive(pid: int) -> bool:
    """Checks if a process ID is currently running on the local system."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == still_active
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False
    except Exception as e:
        logger.debug("Error inspecting process status for PID %s: %s", pid, e)
        return True


def _check_stale_lock(lock_path: Path) -> bool:
    """Returns True if the lock file is stale (owner process dead or lease expired)."""
    if not lock_path.exists():
        return False
    try:
        content = lock_path.read_text(encoding="utf-8")
        parsed: dict[str, str] = {}
        for line in content.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                parsed[k.strip()] = v.strip()
        pid = int(parsed.get("pid", 0))
        ts = float(parsed.get("ts", 0.0))
        # 1. Lease expiration check
        if time.time() - ts > LOCK_LEASE_SECONDS:
            return True
        # 2. Dead process check
        if pid > 0 and not _is_process_alive(pid):
            return True
    except Exception as e:
        logger.debug("Error checking lock staleness for %s: %s", lock_path, e)
        try:
            if time.time() - lock_path.stat().st_mtime > 10.0:
                return True
        except (OSError, Exception) as mtime_err:
            logger.debug("Error checking lock mtime for %s: %s", lock_path, mtime_err)
    return False


class PerRunCertificationLock:
    """
    Exclusive per-run certification lock.
    Thread-safe and process-safe lock using in-memory and filesystem markers.
    Includes automated stale-owner recovery for process crashes and expired leases (T9).
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
        if not lock_file.exists():
            return False
        if _check_stale_lock(lock_file):
            try:
                lock_file.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

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
                if _check_stale_lock(self.lock_file):
                    logger.warning(
                        "Breaking stale certification lock for run '%s' "
                        "(owner PID died or lease expired)",
                        self.run_id,
                    )
                    try:
                        self.lock_file.unlink(missing_ok=True)
                        break
                    except OSError as e:
                        logger.debug("Failed breaking stale lock %s: %s", self.lock_file, e)
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
