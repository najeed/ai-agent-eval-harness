"""Provider-owned certification lease contract."""

import pytest

from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.reference.local_run_store import LocalFileRunStore


def test_provider_lease_is_fenced_and_released(tmp_path):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-1", "scenario", context={"org_id": "a"})
    lock = PerRunCertificationLock("run-1", run_store=store, context={"org_id": "a"})

    lock.acquire()
    assert store.is_certification_leased("run-1", context={"org_id": "a"})
    lock.verify_active()
    assert PerRunCertificationLock.is_locked("run-1", run_store=store, context={"org_id": "a"})
    lock.release()
    assert not store.is_certification_leased("run-1", context={"org_id": "a"})


def test_provider_lease_enforces_scope_and_conflict(tmp_path):
    store = LocalFileRunStore(tmp_path)
    context = {"org_id": "a"}
    store.create_run("run-1", "scenario", context=context)
    first = PerRunCertificationLock("run-1", timeout_seconds=0.01, run_store=store, context=context)
    second = PerRunCertificationLock(
        "run-1", timeout_seconds=0.01, run_store=store, context=context
    )
    first.acquire()
    try:
        with pytest.raises(TimeoutError, match="CertificationLockConflict"):
            second.acquire()
        assert not store.acquire_certification_lease(
            "run-1",
            owner_id="other",
            fencing_token="other",
            timeout_seconds=0,
            context={"org_id": "other"},
        )
    finally:
        first.release()


def test_lock_releases_provider_lease_if_finalizing_transition_fails(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-transition-failure", "scenario")

    def fail_transition(*_args, **_kwargs):
        raise RuntimeError("lifecycle write failed")

    monkeypatch.setattr("eval_runner.run_lifecycle.transition_run_lifecycle", fail_transition)
    lock = PerRunCertificationLock("run-transition-failure", run_store=store)
    with pytest.raises(RuntimeError, match="lifecycle write failed"):
        lock.acquire()
    assert not store.is_certification_leased("run-transition-failure")


def test_expired_provider_lease_is_reclaimed_and_old_fence_is_rejected(tmp_path):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-expired-lease", "scenario")
    assert store.acquire_certification_lease(
        "run-expired-lease",
        owner_id="first-owner",
        fencing_token="first-fence",
        timeout_seconds=0.01,
    )
    vault = store._get_run_vault("run-expired-lease")
    lease = store._read_json(store._lease_path(vault))
    lease["expires_at"] = 0
    store._write_json_durable(store._lease_path(vault), lease)

    assert store.acquire_certification_lease(
        "run-expired-lease",
        owner_id="second-owner",
        fencing_token="second-fence",
        timeout_seconds=0.01,
    )
    assert not store.verify_certification_lease(
        "run-expired-lease", owner_id="first-owner", fencing_token="first-fence"
    )


def test_lock_initialization_requires_run_store():
    with pytest.raises(ValueError, match="RunStorageProvider is required"):
        PerRunCertificationLock("run-none", run_store=None)


def test_is_locked_edge_cases(tmp_path):
    assert not PerRunCertificationLock.is_locked("")
    assert not PerRunCertificationLock.is_locked("run-not-there", run_store=None)

    store = LocalFileRunStore(tmp_path)
    store.create_run("run-active-check", "scenario")
    assert not PerRunCertificationLock.is_locked("run-active-check", run_store=store)

    lock = PerRunCertificationLock("run-active-check", run_store=store)
    lock.acquire()
    try:
        assert PerRunCertificationLock.is_locked("run-active-check", run_store=None)
    finally:
        lock.release()


def test_verify_active_failure_modes(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-verify", "scenario")
    lock = PerRunCertificationLock("run-verify", run_store=store)

    # 1. Not acquired yet
    with pytest.raises(RuntimeError, match="CertificationLockStolen"):
        lock.verify_active()

    # 2. Existing lease failure
    lock._lease_failure = RuntimeError("SimulatedLeaseFailure")
    with pytest.raises(RuntimeError, match="SimulatedLeaseFailure"):
        lock.verify_active()
    lock._lease_failure = None

    # 3. Renew returns False
    lock.acquire()
    try:
        monkeypatch.setattr(lock, "_renew_lease", lambda: False)
        with pytest.raises(RuntimeError, match="CertificationLockStolen"):
            lock.verify_active()
    finally:
        monkeypatch.undo()
        lock.release()

    # 4. verify_certification_lease returns False
    lock.acquire()
    try:
        monkeypatch.setattr(store, "verify_certification_lease", lambda *a, **k: False)
        with pytest.raises(RuntimeError, match="CertificationLockStolen"):
            lock.verify_active()
    finally:
        monkeypatch.undo()
        lock.release()


def test_heartbeat_renewal_failure_and_stolen(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-hb", "scenario")
    lock = PerRunCertificationLock("run-hb", timeout_seconds=1.0, run_store=store)

    # 1. Test heartbeat renewal success loop branch (renewed=True, then stop.wait=True)
    calls = 0

    def mock_wait_success(_t):
        nonlocal calls
        calls += 1
        return calls > 1

    monkeypatch.setattr(lock, "_renew_lease", lambda: True)
    monkeypatch.setattr(lock._heartbeat_stop, "wait", mock_wait_success)
    lock._heartbeat()
    assert lock._lease_failure is None

    # 2. Test heartbeat exception
    def fail_renew():
        raise ConnectionError("Network down")

    monkeypatch.setattr(lock, "_renew_lease", fail_renew)
    calls = 0
    monkeypatch.setattr(lock._heartbeat_stop, "wait", lambda _t: False)
    lock._heartbeat()
    assert isinstance(lock._lease_failure, RuntimeError)
    assert "CertificationLeaseRenewalFailed" in str(lock._lease_failure)
    assert isinstance(lock._lease_failure.__cause__, ConnectionError)

    # 3. Test heartbeat unrenewed (stolen)
    lock._lease_failure = None
    monkeypatch.setattr(lock, "_renew_lease", lambda: False)
    lock._heartbeat()
    assert isinstance(lock._lease_failure, RuntimeError)
    assert "CertificationLockStolen" in str(lock._lease_failure)


def test_reentrant_acquire_and_release(tmp_path):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-reentrant", "scenario")
    lock = PerRunCertificationLock("run-reentrant", run_store=store)

    # Re-entrant acquire
    lock.acquire()
    key = (lock.owner_id, __import__("threading").get_ident())
    assert PerRunCertificationLock._depth[key] == 1

    lock.acquire()
    assert PerRunCertificationLock._depth[key] == 2

    # Re-entrant release
    lock.release()
    assert PerRunCertificationLock._depth[key] == 1
    assert lock._acquired is True

    lock.release()
    assert key not in PerRunCertificationLock._depth
    assert lock._acquired is False


def test_thread_lock_timeout_and_unacquired_release(tmp_path):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-conflict-thread", "scenario")
    lock = PerRunCertificationLock("run-conflict-thread", timeout_seconds=0.01, run_store=store)

    # Unacquired release should safely no-op without errors
    assert not lock._acquired
    lock.release()

    # Simulate thread lock held by another thread
    import threading

    barrier = threading.Barrier(2)

    def hold_lock():
        lock._thread_lock.acquire()
        barrier.wait()
        time.sleep(0.05)
        lock._thread_lock.release()

    import time

    t = threading.Thread(target=hold_lock, daemon=True)
    t.start()
    barrier.wait()

    with pytest.raises(TimeoutError, match="could not lock"):
        lock.acquire()
    t.join()


def test_acquire_failure_after_registration_and_release_failure(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-registered-fail", "scenario")
    lock = PerRunCertificationLock("run-registered-fail", run_store=store)

    def fail_start_heartbeat():
        raise RuntimeError("Heartbeat startup failed")

    monkeypatch.setattr(lock, "_start_heartbeat", fail_start_heartbeat)

    def fail_release(*a, **k):
        raise OSError("Disk unmounted")

    monkeypatch.setattr(store, "release_certification_lease", fail_release)

    with pytest.raises(RuntimeError, match="Heartbeat startup failed"):
        lock.acquire()

    assert not lock._acquired
    key = (lock.owner_id, __import__("threading").get_ident())
    assert key not in PerRunCertificationLock._depth
    assert "run-registered-fail" not in PerRunCertificationLock._active_locks


def test_context_manager_protocol(tmp_path):
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-ctx", "scenario")

    with PerRunCertificationLock("run-ctx", run_store=store) as lock:
        assert lock._acquired
        assert store.is_certification_leased("run-ctx")

    assert not lock._acquired
    assert not store.is_certification_leased("run-ctx")
