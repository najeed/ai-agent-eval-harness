"""
Comprehensive unit tests for eval_runner/certification_lock.py.

Covers:
- Process liveness checks on Windows and POSIX
- Lock metadata reading (JSON, malformed JSON fallback, key=value, error handling)
- Stale lock detection and reclamation
- Re-entrant locking semantics
- Thread lock acquisition timeout
- Lock file wait timeout
- Active lock verification and stolen lock detection
- Safe release with owner token validation and error handling
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.certification_lock import (
    PerRunCertificationLock,
    _is_lock_stale,
    _is_process_alive,
    _read_lock_data,
)


def test_is_process_alive_boundaries(monkeypatch):
    # 1. Non-positive PID
    assert _is_process_alive(0) is False
    assert _is_process_alive(-1) is False

    # 2. Windows current process
    assert _is_process_alive(os.getpid()) is True

    # 3. Windows non-existent process
    assert _is_process_alive(99999999) is False

    # 4. POSIX emulation
    monkeypatch.setattr(os, "name", "posix")

    with patch("os.kill", return_value=None):
        assert _is_process_alive(1234) is True

    with patch("os.kill", side_effect=ProcessLookupError):
        assert _is_process_alive(1234) is False

    with patch("os.kill", side_effect=RuntimeError("Kernel error")):
        assert _is_process_alive(1234) is True


def test_read_lock_data_formats_and_errors(tmp_path):
    nonexistent = tmp_path / "missing.lock"
    assert _read_lock_data(nonexistent) == {}

    # Valid JSON
    json_lock = tmp_path / "valid_json.lock"
    json_lock.write_text(json.dumps({"pid": "100", "owner_id": "test_owner"}), encoding="utf-8")
    assert _read_lock_data(json_lock) == {"pid": "100", "owner_id": "test_owner"}

    # Malformed JSON with braces (starts with { and ends with })
    fallback_lock = tmp_path / "malformed.lock"
    fallback_lock.write_text("{\nnot_valid_json = 1\n}", encoding="utf-8")
    data = _read_lock_data(fallback_lock)
    assert data["not_valid_json"] == "1"

    # Standard key=value
    kv_lock = tmp_path / "kv.lock"
    kv_lock.write_text("owner_id=abc\npid=555\n", encoding="utf-8")
    assert _read_lock_data(kv_lock) == {"owner_id": "abc", "pid": "555"}

    # File read exception
    unreadable = tmp_path / "unreadable.lock"
    unreadable.write_text("content", encoding="utf-8")
    with patch.object(type(unreadable), "read_text", side_effect=PermissionError("Locked")):
        assert _read_lock_data(unreadable) == {}


def test_is_lock_stale_logic(tmp_path):
    missing_lock = tmp_path / "none.lock"
    assert _is_lock_stale(missing_lock) is False

    alive_lock = tmp_path / "alive.lock"
    alive_lock.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    assert _is_lock_stale(alive_lock) is False

    dead_lock = tmp_path / "dead.lock"
    dead_lock.write_text("pid=99999999\n", encoding="utf-8")
    with patch("eval_runner.certification_lock._is_process_alive", return_value=False):
        assert _is_lock_stale(dead_lock) is True


def test_per_run_certification_lock_is_locked_branches(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    # 1. Empty run_id
    assert PerRunCertificationLock.is_locked("") is False

    # 2. Active in memory
    run_id = "test_run_mem"
    with PerRunCertificationLock._meta_lock:
        PerRunCertificationLock._active_locks.add(run_id)
    try:
        assert PerRunCertificationLock.is_locked(run_id) is True
    finally:
        with PerRunCertificationLock._meta_lock:
            PerRunCertificationLock._active_locks.discard(run_id)

    # 3. Missing file
    assert PerRunCertificationLock.is_locked("nonexistent_run") is False

    # 4. Stale lock file on disk unlinked
    stale_run = "stale_run"
    stale_dir = tmp_path / stale_run
    stale_dir.mkdir(parents=True, exist_ok=True)
    stale_file = stale_dir / ".certification.lock"
    stale_file.write_text("pid=999999\n", encoding="utf-8")

    with patch("eval_runner.certification_lock._is_lock_stale", return_value=True):
        assert PerRunCertificationLock.is_locked(stale_run) is False
        assert not stale_file.exists()

    # 5. Stale lock unlink raises OSError
    stale_file.write_text("pid=999999\n", encoding="utf-8")
    with patch("eval_runner.certification_lock._is_lock_stale", return_value=True):
        with patch.object(type(stale_file), "unlink", side_effect=OSError("Cannot unlink")):
            assert PerRunCertificationLock.is_locked(stale_run) is False

    # 6. Active lock file on disk
    active_run = "active_run"
    active_dir = tmp_path / active_run
    active_dir.mkdir(parents=True, exist_ok=True)
    active_file = active_dir / ".certification.lock"
    active_file.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    with patch("eval_runner.certification_lock._is_lock_stale", return_value=False):
        assert PerRunCertificationLock.is_locked(active_run) is True


def test_per_run_certification_lock_verify_active(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    lock = PerRunCertificationLock("run_verify_test", timeout_seconds=1.0)

    # 1. Not acquired
    with pytest.raises(RuntimeError, match="LockNotHeld"):
        lock.verify_active()

    # 2. Acquired and valid
    with lock:
        lock.verify_active()

        # 3. Lock overwritten by another owner
        lock.lock_file.write_text("owner_id=intruder\nfencing_token=stolen\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="CertificationLockStolen"):
            lock.verify_active()


def test_per_run_certification_lock_reentrant_acquire_release(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    lock = PerRunCertificationLock("reentrant_run", timeout_seconds=1.0)

    with lock:
        # Re-entrant acquire on the same instance
        with lock:
            assert lock._acquired is True
            lock.verify_active()
        # Outer lock remains held
        assert lock._acquired is True
        lock.verify_active()


def test_per_run_certification_lock_thread_acquisition_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    lock = PerRunCertificationLock("thread_fail_run", timeout_seconds=0.1)
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False
    lock._thread_lock = mock_lock

    with pytest.raises(TimeoutError, match="could not acquire thread lock"):
        lock.acquire()


def test_per_run_certification_lock_stale_reclaim_and_wait_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    run_dir = tmp_path / "stale_acquire_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_file = run_dir / ".certification.lock"
    lock_file.write_text("pid=999999\n", encoding="utf-8")

    # 1. Stale reclaim: successfully breaks stale lock
    lock = PerRunCertificationLock("stale_acquire_run", timeout_seconds=0.5)
    with patch("eval_runner.certification_lock._is_lock_stale", return_value=True):
        with lock:
            assert lock._acquired is True

    # 2. Stale reclaim: unlink raises OSError, handled and retried
    lock_err = PerRunCertificationLock("stale_oserr_run", timeout_seconds=0.5)
    err_dir = tmp_path / "stale_oserr_run"
    err_dir.mkdir(parents=True, exist_ok=True)
    err_file = err_dir / ".certification.lock"
    err_file.write_text("pid=999999\n", encoding="utf-8")

    call_count = 0
    original_unlink = Path.unlink

    def _unlink_once_fail(self, *args, **kwargs):
        nonlocal call_count
        if self == err_file:
            call_count += 1
            if call_count == 1:
                raise OSError("Access denied")
        return original_unlink(self, *args, **kwargs)

    with patch("eval_runner.certification_lock._is_lock_stale", return_value=True):
        with patch.object(Path, "unlink", _unlink_once_fail):
            with lock_err:
                assert lock_err._acquired is True

    # 3. Active lock held by other process triggers wait timeout
    lock_file.write_text("pid=12345\n", encoding="utf-8")
    lock_timeout = PerRunCertificationLock("stale_acquire_run", timeout_seconds=0.1)
    with patch("eval_runner.certification_lock._is_lock_stale", return_value=False):
        with pytest.raises(TimeoutError, match="timed out waiting for run"):
            lock_timeout.acquire()

    # 3. Lifecycle transition exception during acquire fails closed
    lock_lifecycle = PerRunCertificationLock("lifecycle_run", timeout_seconds=1.0)
    with patch(
        "eval_runner.run_lifecycle.transition_run_lifecycle",
        side_effect=RuntimeError("Lifecycle crash"),
    ):
        with pytest.raises(RuntimeError, match="Lifecycle crash"):
            lock_lifecycle.acquire()
        assert lock_lifecycle._acquired is False
        assert lock_lifecycle._fd is None


def test_per_run_certification_lock_release_anomalies(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    # 1. Release when lock file unlink raises OSError
    lock = PerRunCertificationLock("release_anom_run", timeout_seconds=1.0)
    with lock:
        pass
    # Now simulate unlink error on exit
    lock2 = PerRunCertificationLock("release_anom_run2", timeout_seconds=1.0)
    lock2.acquire()
    with patch.object(type(lock2.lock_file), "unlink", side_effect=OSError("Unlink fail")):
        lock2.release()

    lock_acquired = PerRunCertificationLock("release_foreign_run", timeout_seconds=1.0)
    with lock_acquired:
        lock_acquired.lock_file.write_text("owner_id=foreign_owner\n", encoding="utf-8")


def test_per_run_certification_lock_full_branch_matrix(tmp_path, monkeypatch):
    """Exhaustively cover remaining edge branches in certification_lock.py."""
    import sys

    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    # 1. _read_lock_data with non-dict JSON (json.loads returns non-dict)
    nondict_file = tmp_path / "nondict_obj.lock"
    nondict_file.write_text("{\nfallback_k=fallback_v\n}", encoding="utf-8")
    with patch("json.loads", return_value="a string not a dict"):
        res = _read_lock_data(nondict_file)
        assert res.get("fallback_k") == "fallback_v"

    # Corrupt JSON decode error
    corrupt_json_file = tmp_path / "corrupt.lock"
    corrupt_json_file.write_text("{not valid json: true}\nfallback_k=fallback_v", encoding="utf-8")
    res = _read_lock_data(corrupt_json_file)
    assert res.get("fallback_k") == "fallback_v"

    # 2. Windows msvcrt.locking error during acquire and release
    if os.name == "nt":
        import msvcrt

        lock_nt_fail = PerRunCertificationLock("nt_fail_run", timeout_seconds=0.1)
        with patch.object(msvcrt, "locking", side_effect=OSError("Lock error")):
            with pytest.raises(TimeoutError):
                lock_nt_fail.acquire()

        # Unlock OSError during release
        lock_nt_unlock = PerRunCertificationLock("nt_unlock_run", timeout_seconds=1.0)
        lock_nt_unlock.acquire()
        orig_locking = msvcrt.locking

        def _fail_unlock(fd, mode, nbytes):
            if mode == msvcrt.LK_UNLCK:
                raise OSError("Unlock failed")
            return orig_locking(fd, mode, nbytes)

        with patch.object(msvcrt, "locking", side_effect=_fail_unlock):
            lock_nt_unlock.release()

    # 3. POSIX flock path during acquire and release
    mock_fcntl = MagicMock()
    with patch.dict(sys.modules, {"fcntl": mock_fcntl}):
        with patch("os.name", "posix"):
            lock_posix = PerRunCertificationLock("posix_run", timeout_seconds=1.0)
            lock_posix.acquire()
            assert mock_fcntl.flock.called
            lock_posix.release()

            # POSIX flock error during acquire
            lock_posix_fail = PerRunCertificationLock("posix_fail_run", timeout_seconds=0.1)
            mock_fcntl.flock.side_effect = OSError("flock busy")
            with pytest.raises(TimeoutError):
                lock_posix_fail.acquire()

            # POSIX flock error during release
            lock_posix_rel = PerRunCertificationLock("posix_rel_err_run", timeout_seconds=1.0)
            mock_fcntl.flock.side_effect = None
            lock_posix_rel.acquire()
            mock_fcntl.flock.side_effect = OSError("flock unlock error")
            lock_posix_rel.release()

    # 4. Error during write after open: fd is not None, close raises OSError
    lock_write_err = PerRunCertificationLock("write_err_run", timeout_seconds=0.1)
    with patch("os.write", side_effect=OSError("Disk write error")):
        with patch("os.close", side_effect=OSError("Close error")):
            with pytest.raises(TimeoutError):
                lock_write_err.acquire()

    # 5. Error closing fd during release finally
    lock_rel_close_err = PerRunCertificationLock("rel_close_err_run", timeout_seconds=1.0)
    lock_rel_close_err.acquire()
    with patch("os.close", side_effect=OSError("Close error")):
        lock_rel_close_err.release()

    # 6. Release when lock file does not exist (branch 294 -> 310)
    lock_missing_file = PerRunCertificationLock("missing_file_run", timeout_seconds=1.0)
    lock_missing_file.acquire()
    with patch.object(type(lock_missing_file.lock_file), "exists", return_value=False):
        lock_missing_file.release()

    # 7. Release when self._fd is None and lock._acquired is False (branches 270->294, 313->exit)
    lock_unacquired = PerRunCertificationLock("unacquired_run", timeout_seconds=1.0)
    assert lock_unacquired._fd is None
    assert lock_unacquired._acquired is False
    lock_unacquired.release()
