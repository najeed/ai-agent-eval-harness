"""
eval_runner.certification_lock
Exclusive per-run certification lock spanning outcome extraction -> freeze -> sign -> seal.

Guarantees transactional mutual exclusion during certification:
1. Prevents concurrent trace appends/writes during certification.
2. Eliminates TOCTOU race conditions between outcome extraction and trace sealing.
3. Uses monotonic fencing tokens to prevent accidental lock stealing.
4. Transitions the run lifecycle into FINALIZING upon acquisition.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

from eval_runner import config

logger = logging.getLogger(__name__)


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


def _read_lock_data(lock_path: Path) -> dict[str, str]:
    """Reads structured metadata from a lock file (supports key=value and JSON)."""
    if not lock_path.is_file():
        return {}
    try:
        content = lock_path.read_text(encoding="utf-8").strip()
        if content.startswith("{") and content.endswith("}"):
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except (ValueError, UnicodeDecodeError) as json_err:
                logger.debug(
                    "Lock file at %s is not valid JSON, falling back to key=value: %s",
                    lock_path,
                    json_err,
                )
        parsed: dict[str, str] = {}
        for line in content.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                parsed[k.strip()] = v.strip()
        return parsed
    except Exception as e:
        logger.debug("Error reading lock data from %s: %s", lock_path, e)
        return {}


def _is_lock_stale(lock_path: Path) -> bool:
    """
    Checks if a lock file belongs to a dead process.
    Never steals a lock from an active running process.
    """
    data = _read_lock_data(lock_path)
    if not data:
        return False
    pid = int(data.get("pid", 0))
    if pid > 0 and not _is_process_alive(pid):
        return True
    return False


class PerRunCertificationLock:
    """
    Exclusive per-run certification lock with monotonic fencing tokens.
    Guarantees that active holders cannot have their locks stolen.
    """

    _thread_locks: ClassVar[dict[str, threading.RLock]] = {}
    _meta_lock: ClassVar[threading.Lock] = threading.Lock()
    _active_locks: ClassVar[set[str]] = set()
    _thread_depth: ClassVar[dict[tuple[str, int], int]] = {}

    def __init__(self, run_id: str, timeout_seconds: float = 10.0) -> None:
        self.run_id = run_id
        self.timeout_seconds = timeout_seconds
        self.owner_id = f"pid_{os.getpid()}_th_{threading.get_ident()}_{uuid.uuid4().hex[:6]}"
        self.fencing_token = f"fence_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        with self._meta_lock:
            if run_id not in self._thread_locks:
                self._thread_locks[run_id] = threading.RLock()
            self._thread_lock = self._thread_locks[run_id]
        self.lock_dir = config.RUN_LOG_DIR / run_id
        self.lock_file = self.lock_dir / ".certification.lock"
        self._acquired = False
        self._fd: int | None = None

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
        if _is_lock_stale(lock_file):
            try:
                lock_file.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

    def verify_active(self) -> None:
        """Validates that this instance still owns the active lock."""
        if not self._acquired:
            raise RuntimeError(f"LockNotHeld: Lock for run '{self.run_id}' is not acquired")
        data = _read_lock_data(self.lock_file)
        if data.get("owner_id") != self.owner_id or data.get("fencing_token") != self.fencing_token:
            raise RuntimeError(
                f"CertificationLockStolen: Lock for run '{self.run_id}' was superseded or stolen"
            )

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
            content = (
                f"owner_id={self.owner_id}\n"
                f"fencing_token={self.fencing_token}\n"
                f"pid={os.getpid()}\n"
                f"ts={time.time()}\n"
                f"run_id={self.run_id}\n"
            ).encode()

            fd: int | None = None
            while True:
                if self.lock_file.exists() and _is_lock_stale(self.lock_file):
                    logger.warning(
                        "Reclaiming stale certification lock for run '%s' (owner PID died)",
                        self.run_id,
                    )
                    try:
                        self.lock_file.unlink(missing_ok=True)
                    except OSError as e:
                        logger.debug("Failed breaking stale lock %s: %s", self.lock_file, e)

                try:
                    fd = os.open(
                        str(self.lock_file),
                        os.O_CREAT | os.O_EXCL | os.O_RDWR,
                        0o600,
                    )
                    if os.name == "nt":
                        import msvcrt

                        try:
                            os.lseek(fd, 1048576, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                            os.lseek(fd, 0, os.SEEK_SET)
                        except OSError as lock_err:
                            os.close(fd)
                            fd = None
                            raise lock_err
                    else:
                        import fcntl

                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except OSError as lock_err:
                            os.close(fd)
                            fd = None
                            raise lock_err

                    os.write(fd, content)
                    os.fsync(fd)
                    self._fd = fd
                    break
                except (FileExistsError, OSError) as err:
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        fd = None

                    if time.monotonic() - start_time > self.timeout_seconds:
                        raise TimeoutError(
                            f"CertificationLockConflict: timed out waiting for run '{self.run_id}' "
                            f"(held by PID {_read_lock_data(self.lock_file).get('pid', 'unknown')})"
                        ) from err
                    time.sleep(0.05)

            from eval_runner.run_lifecycle import RunLifecycleState, transition_run_lifecycle

            try:
                transition_run_lifecycle(
                    self.run_id,
                    RunLifecycleState.FINALIZING,
                    metadata={"fencing_token": self.fencing_token, "owner_id": self.owner_id},
                )
            except Exception as tr_err:
                logger.error(
                    "Failed transitioning lifecycle to FINALIZING for %s: %s", self.run_id, tr_err
                )
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None
                    try:
                        self.lock_file.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise

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
            if self._fd is not None:
                try:
                    if os.name == "nt":
                        import msvcrt

                        try:
                            os.lseek(self._fd, 1048576, os.SEEK_SET)
                            msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                        except OSError:
                            pass
                    else:
                        import fcntl

                        try:
                            fcntl.flock(self._fd, fcntl.LOCK_UN)
                        except OSError:
                            pass
                finally:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None

            if self.lock_file.exists():
                data = _read_lock_data(self.lock_file)
                # Fencing token / owner validation: only delete if WE own it
                if (
                    data.get("owner_id") == self.owner_id
                    and data.get("fencing_token") == self.fencing_token
                ):
                    try:
                        self.lock_file.unlink(missing_ok=True)
                    except OSError as e:
                        logger.debug("Failed unlinking lock for %s: %s", self.run_id, e)
                else:
                    logger.warning(
                        "Cannot release certification lock for '%s': owned by another token",
                        self.run_id,
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


__all__ = ["PerRunCertificationLock"]
