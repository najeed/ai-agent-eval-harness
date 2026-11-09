"""Unit tests for atomic lease renewal, mutation fencing, and post-seal immutability.

Verifies remediations for P0-1 (atomic lease renewal) and P0-2 (mutation fencing).
"""

import time
from pathlib import Path

import pytest

from eval_runner.reference.local_run_store import LocalFileRunStore, RunManifestImmutableError


@pytest.fixture
def run_store(tmp_path: Path) -> LocalFileRunStore:
    return LocalFileRunStore(log_dir=tmp_path / "runs")


def test_atomic_lease_renewal_rejects_stale_expired_ownership(run_store: LocalFileRunStore):
    """P0-1: Expired owner cannot overwrite a successor's lease during renewal."""
    run_id = "test-run-lease-expiry"
    run_store.create_run(run_id, scenario_id="scenario-1")

    owner_a = "owner-process-A"
    fence_a = "fence-token-A"
    owner_b = "owner-process-B"
    fence_b = "fence-token-B"

    # 1. Owner A acquires lease with minimal TTL (overwritten manually to expired)
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner_a, fencing_token=fence_a, timeout_seconds=60.0
    )

    vault = run_store._get_run_vault(run_id)
    lease_path = run_store._lease_path(vault)
    lease_data = run_store._read_json(lease_path)
    assert lease_data is not None

    # Simulate expiration of Owner A's lease
    lease_data["expires_at"] = time.time() - 10.0
    run_store._write_json_durable(lease_path, lease_data)

    # 2. Owner B acquires the expired lease
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner_b, fencing_token=fence_b, timeout_seconds=120.0
    )
    current_lease = run_store._read_json(lease_path)
    assert current_lease["owner_id"] == owner_b
    assert current_lease["fencing_token"] == fence_b

    # 3. Stale Owner A attempts renewal -> MUST be rejected
    renewed = run_store.renew_certification_lease(
        run_id, owner_id=owner_a, fencing_token=fence_a, timeout_seconds=60.0
    )
    assert renewed is False

    # Owner B's lease remains intact and untouched
    preserved_lease = run_store._read_json(lease_path)
    assert preserved_lease["owner_id"] == owner_b
    assert preserved_lease["fencing_token"] == fence_b


def test_atomic_lease_renewal_rejects_mismatched_fencing_token(run_store: LocalFileRunStore):
    """P0-1: Renewal with invalid fencing token fails."""
    run_id = "test-run-lease-fence"
    run_store.create_run(run_id, scenario_id="scenario-1")

    owner = "owner-proc"
    fence = "fence-valid"
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner, fencing_token=fence, timeout_seconds=60.0
    )

    # Attempt renewal with wrong token
    assert (
        run_store.renew_certification_lease(
            run_id, owner_id=owner, fencing_token="wrong-fence", timeout_seconds=60.0
        )
        is False
    )

    # Attempt renewal with valid credentials succeeds
    assert run_store.renew_certification_lease(
        run_id, owner_id=owner, fencing_token=fence, timeout_seconds=60.0
    )


def test_atomic_lease_renewal_on_missing_run_or_lease(run_store: LocalFileRunStore):
    """P0-1: Renewal fails cleanly when run or lease does not exist."""
    assert (
        run_store.renew_certification_lease(
            "non-existent-run", owner_id="o", fencing_token="f", timeout_seconds=60.0
        )
        is False
    )

    run_id = "test-run-no-lease"
    run_store.create_run(run_id, scenario_id="scenario-1")
    assert (
        run_store.renew_certification_lease(
            run_id, owner_id="o", fencing_token="f", timeout_seconds=60.0
        )
        is False
    )


def test_post_seal_status_mutation_rejected(run_store: LocalFileRunStore):
    """P0-2: Sealed run cannot have status mutated."""
    run_id = "test-run-sealed-mutation"
    run_store.create_run(run_id, scenario_id="scenario-1")
    run_store.seal(run_id)

    # Status mutation on sealed run must raise RunManifestImmutableError
    with pytest.raises(RunManifestImmutableError):
        run_store.update_run_status(run_id, "RUNNING")

    with pytest.raises(RunManifestImmutableError):
        run_store.update_run_status(run_id, "COMPLETED")

    # Idempotent re-seal returns True
    assert run_store.update_run_status(run_id, "SEALED") is True


def test_post_seal_append_events_rejected(run_store: LocalFileRunStore):
    """P0-2: Events cannot be appended to a sealed run."""
    run_id = "test-run-sealed-append"
    run_store.create_run(run_id, scenario_id="scenario-1")
    run_store.seal(run_id)

    with pytest.raises(RunManifestImmutableError):
        run_store.append_events(run_id, [{"event": "agent_thought", "content": "too late"}])


def test_update_run_status_fenced_during_active_certification_lease(
    run_store: LocalFileRunStore,
):
    """P0-2: Unfenced writers cannot mutate status while certification lease is held."""
    run_id = "test-run-fenced-lease"
    run_store.create_run(run_id, scenario_id="scenario-1")

    owner = "cert-worker-1"
    fence = "fence-token-1"
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner, fencing_token=fence, timeout_seconds=60.0
    )

    # Unfenced writer (no details or mismatched credentials) is rejected
    rejected = run_store.update_run_status(run_id, "PAUSED_FOR_APPROVAL")
    assert rejected is False

    rejected_competing = run_store.update_run_status(
        run_id,
        "PAUSED_FOR_APPROVAL",
        details={"owner_id": "other-worker", "fencing_token": "other-fence"},
    )
    assert rejected_competing is False

    # Lease owner with matching credentials is authorized
    accepted = run_store.update_run_status(
        run_id,
        "FINALIZING",
        details={"owner_id": owner, "fencing_token": fence},
    )
    assert accepted is True


def test_release_certification_lease_concurrency(run_store: LocalFileRunStore):
    """P0-1: Lease release validates owner and fencing token under mutation lock."""
    run_id = "test-run-release"
    run_store.create_run(run_id, scenario_id="scenario-1")

    owner = "cert-worker-2"
    fence = "fence-token-2"
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner, fencing_token=fence, timeout_seconds=60.0
    )

    vault = run_store._get_run_vault(run_id)
    legacy_lock = vault / ".certification.lock"
    legacy_lock.write_text('{"pid": 12345}', encoding="utf-8")

    # Mismatched release rejected
    assert (
        run_store.release_certification_lease(run_id, owner_id="wrong", fencing_token=fence)
        is False
    )

    # Valid release succeeds and unlinks legacy lock
    assert run_store.release_certification_lease(run_id, owner_id=owner, fencing_token=fence)
    assert run_store.is_certification_leased(run_id) is False
    assert not legacy_lock.exists()

    # Release when legacy lock does NOT exist covers branch 462 -> 464
    run_no_legacy = "test-run-release-no-legacy"
    run_store.create_run(run_no_legacy, scenario_id="scenario-1")
    assert run_store.acquire_certification_lease(
        run_no_legacy, owner_id="own-nl", fencing_token="fence-nl", timeout_seconds=60.0
    )
    # Manually remove legacy lock created during acquire
    vault_no_legacy = run_store._get_run_vault(run_no_legacy)
    (vault_no_legacy / ".certification.lock").unlink(missing_ok=True)
    assert (
        run_store.release_certification_lease(
            run_no_legacy, owner_id="own-nl", fencing_token="fence-nl"
        )
        is True
    )


def test_acquire_lease_reacquire_same_owner_and_timeouts(run_store: LocalFileRunStore):
    """P0-1: Re-acquisition by same owner extends lease; competitor times out."""
    run_id = "test-run-reacquire"
    run_store.create_run(run_id, scenario_id="scenario-1")

    owner_1 = "owner-1"
    token_1 = "token-1"
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner_1, fencing_token=token_1, timeout_seconds=60.0
    )

    # Re-acquisition by same owner extends lease
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner_1, fencing_token=token_1, timeout_seconds=60.0
    )

    # Competitor times out
    assert (
        run_store.acquire_certification_lease(
            run_id, owner_id="owner-2", fencing_token="token-2", timeout_seconds=0.05
        )
        is False
    )

    # Acquire on non-existent run fails
    assert (
        run_store.acquire_certification_lease(
            "non-existent-run", owner_id="owner-1", fencing_token="token-1", timeout_seconds=1.0
        )
        is False
    )


def test_acquire_lease_legacy_pid_lock_branches(run_store: LocalFileRunStore):
    """P0-1: acquire_certification_lease handles active, dead, and corrupt legacy PID locks."""
    import json
    import os

    run_id = "test-run-legacy-pid-branches"
    run_store.create_run(run_id, scenario_id="s1")
    vault = run_store._get_run_vault(run_id)
    legacy_lock = vault / ".certification.lock"

    # 1. Active PID blocks lease acquisition
    legacy_lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    assert (
        run_store.acquire_certification_lease(
            run_id, owner_id="own-b", fencing_token="tok-b", timeout_seconds=0.05
        )
        is False
    )

    # 2. Dead PID is safely reclaimed and acquisition succeeds
    legacy_lock.write_text(json.dumps({"pid": 999999}), encoding="utf-8")
    assert (
        run_store.acquire_certification_lease(
            run_id, owner_id="own-b", fencing_token="tok-b", timeout_seconds=1.0
        )
        is True
    )
    assert run_store.release_certification_lease(run_id, owner_id="own-b", fencing_token="tok-b")

    # 3. Corrupt/malformed legacy lock handles exception gracefully
    legacy_lock.write_text("not-json", encoding="utf-8")
    assert (
        run_store.acquire_certification_lease(
            run_id, owner_id="own-c", fencing_token="tok-c", timeout_seconds=1.0
        )
        is True
    )
    assert run_store.release_certification_lease(run_id, owner_id="own-c", fencing_token="tok-c")

    # 4. OSError during legacy lock inspection/unlink
    from unittest.mock import patch

    legacy_lock.write_text(json.dumps({"pid": 999999}), encoding="utf-8")
    orig_read_json = run_store._read_json

    def mock_read(p):
        if ".certification.lock" in str(p):
            raise OSError("lock read error")
        return orig_read_json(p)

    with patch.object(run_store, "_read_json", side_effect=mock_read):
        assert (
            run_store.acquire_certification_lease(
                run_id, owner_id="own-d", fencing_token="tok-d", timeout_seconds=1.0
            )
            is True
        )
    assert run_store.release_certification_lease(run_id, owner_id="own-d", fencing_token="tok-d")


def test_release_lease_missing_run_or_lease(run_store: LocalFileRunStore):
    """P0-1: Release fails when run or lease does not exist."""
    assert (
        run_store.release_certification_lease("non-existent-run", owner_id="o", fencing_token="f")
        is False
    )

    run_id = "test-run-empty-lease"
    run_store.create_run(run_id, scenario_id="scenario-1")
    assert run_store.release_certification_lease(run_id, owner_id="o", fencing_token="f") is False


def test_lease_operations_oserror_resilience(
    run_store: LocalFileRunStore, monkeypatch: pytest.MonkeyPatch
):
    """P0-1: OSError during durable lease write or unlink fails gracefully."""
    run_id = "test-run-lease-oserror"
    run_store.create_run(run_id, scenario_id="scenario-1")
    owner = "owner-oserr"
    fence = "fence-oserr"
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner, fencing_token=fence, timeout_seconds=60.0
    )

    # Renew raises OSError on write
    monkeypatch.setattr(
        run_store,
        "_write_json_durable",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk error")),
    )
    assert (
        run_store.renew_certification_lease(
            run_id, owner_id=owner, fencing_token=fence, timeout_seconds=60.0
        )
        is False
    )

    # Release raises OSError on unlink
    monkeypatch.undo()
    monkeypatch.setattr(
        run_store,
        "_unlink_durable",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk error")),
    )
    assert (
        run_store.release_certification_lease(run_id, owner_id=owner, fencing_token=fence) is False
    )


def test_append_events_mutation_branches(run_store: LocalFileRunStore):
    """P0-2: Verify append_events empty guard, lifecycle immutability, and auto-creation."""
    run_id = "test-run-append-branches"

    # Empty events list returns 0 immediately
    assert run_store.append_events(run_id, []) == 0

    # Auto-creates run when record does not yet exist
    assert run_store.append_events(run_id, [{"type": "start", "seq": 1}]) == 1
    assert run_store.get_run(run_id) is not None

    # Status in PAUSED_FOR_APPROVAL or FINALIZING forbids appending events
    run_store.update_run_status(run_id, "PAUSED_FOR_APPROVAL")
    with pytest.raises(RunManifestImmutableError):
        run_store.append_events(run_id, [{"type": "event2", "seq": 2}])

    run_store.update_run_status(run_id, "FINALIZING")
    with pytest.raises(RunManifestImmutableError):
        run_store.append_events(run_id, [{"type": "event3", "seq": 3}])


def test_update_run_status_context_and_evidence_failure(run_store: LocalFileRunStore):
    """P0-2: Verify context checks and evidence capture failure constraints in update_run_status."""
    run_id = "test-run-status-constraints"
    run_store.create_run(run_id, scenario_id="scenario-1", context={"tenant": "corp1"})

    # Context mismatch returns False
    assert run_store.update_run_status(run_id, "RUNNING", context={"tenant": "corp2"}) is False

    # Evidence capture failure flag restricts valid transition to CERTIFICATION_FAILED
    run_store.update_run_status(run_id, "RUNNING", details={"evidence_capture_failed": True})
    # Attempting to transition to COMPLETED while evidence failed returns False
    assert run_store.update_run_status(run_id, "COMPLETED") is False

    # Transitioning to CERTIFICATION_FAILED succeeds
    assert run_store.update_run_status(run_id, "CERTIFICATION_FAILED") is True


def test_update_run_status_oserror_handling(
    run_store: LocalFileRunStore, monkeypatch: pytest.MonkeyPatch
):
    """P0-2: Verify update_run_status handles OSError when persisting lifecycle or markers."""
    run_id = "test-run-lifecycle-oserror"
    run_store.create_run(run_id, scenario_id="scenario-1")

    # Fail write_bytes_durable for lifecycle
    orig_write = run_store._write_bytes_durable

    def mock_write(path, data):
        if str(path).endswith(".run_lifecycle") or str(path).endswith(".sealed"):
            raise OSError("disk write error")
        return orig_write(path, data)

    monkeypatch.setattr(run_store, "_write_bytes_durable", mock_write)
    assert run_store.update_run_status(run_id, "RUNNING") is False


def test_delete_run_sealed_rejection(run_store: LocalFileRunStore):
    """P0-2: Deleting a sealed run raises RunManifestImmutableError."""
    run_id = "test-run-delete-sealed"
    run_store.create_run(run_id, scenario_id="scenario-1")
    run_store.seal(run_id)

    with pytest.raises(RunManifestImmutableError):
        run_store.delete_run(run_id)

    # Deleting non-existent run returns False
    assert run_store.delete_run("non-existent-run-for-delete") is False

    # Deleting invalid/path traversal run returns False
    assert run_store.delete_run("../../escape-path") is False


def test_mutation_lock_reentrancy(tmp_path: Path):
    """P0-2: Verify _LocalMutationLock re-entrancy within same thread."""
    from eval_runner.reference.local_run_store import _LocalMutationLock

    vault = tmp_path / "lock_vault"
    vault.mkdir(parents=True, exist_ok=True)

    # Nested re-entrant acquisition in same thread
    with _LocalMutationLock.acquire(vault):
        with _LocalMutationLock.acquire(vault):
            # Nested depth > 0, lock held cleanly
            pass


def test_acquire_lease_legacy_lock_oserror(
    run_store: LocalFileRunStore, monkeypatch: pytest.MonkeyPatch
):
    """P0-1: acquire_certification_lease handles legacy lock write failure gracefully."""
    run_id = "test-run-legacy-oserr"
    run_store.create_run(run_id, scenario_id="s1")

    orig_write_text = Path.write_text

    def mock_write(path_obj, *args, **kwargs):
        if ".certification.lock" in str(path_obj):
            raise OSError("permission denied")
        return orig_write_text(path_obj, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", mock_write)
    assert (
        run_store.acquire_certification_lease(
            run_id, owner_id="own1", fencing_token="tok1", timeout_seconds=60.0
        )
        is True
    )


def test_renew_lease_expired_direct_rejection(run_store: LocalFileRunStore):
    """P0-1: renew_certification_lease fails if lease expired before competitor acquires."""
    run_id = "test-run-renew-expired"
    run_store.create_run(run_id, scenario_id="s1")

    assert run_store.acquire_certification_lease(
        run_id, owner_id="own1", fencing_token="tok1", timeout_seconds=60.0
    )
    vault = run_store._get_run_vault(run_id)
    lease_p = run_store._lease_path(vault)
    lease_data = run_store._read_json(lease_p)
    lease_data["expires_at"] = time.time() - 100.0
    run_store._write_json_durable(lease_p, lease_data)

    # Direct renewal while expired returns False
    assert (
        run_store.renew_certification_lease(
            run_id, owner_id="own1", fencing_token="tok1", timeout_seconds=60.0
        )
        is False
    )


def test_update_run_status_sealed_write_oserror_and_missing_record(
    run_store: LocalFileRunStore, monkeypatch: pytest.MonkeyPatch
):
    """P0-2: update_run_status creates missing record and handles sealed write OSError."""
    run_id = "test-run-sealed-oserr"
    run_store._get_run_vault(run_id, create=True)

    # update_run_status when record is None auto-creates it
    assert run_store.update_run_status(run_id, "RUNNING") is True
    assert run_store.get_run(run_id) is not None

    # Fail write for .sealed
    orig_write = run_store._write_bytes_durable

    def mock_write(p, data):
        if str(p).endswith(".sealed"):
            raise OSError("cannot write sealed")
        return orig_write(p, data)

    monkeypatch.setattr(run_store, "_write_bytes_durable", mock_write)
    assert run_store.update_run_status(run_id, "SEALED") is False


def test_save_run_manifest_branches(run_store: LocalFileRunStore):
    """P0-2: Verify save_run_manifest lifecycle and revision branches."""
    run_id = "test-run-manifest-branches"
    run_store.create_run(run_id, scenario_id="s1")

    # 1. Lifecycle FINALIZING raises RunManifestImmutableError
    run_store.update_run_status(run_id, "FINALIZING")
    manifest_v1 = {"run_id": run_id, "version": "1.0.0"}
    with pytest.raises(RunManifestImmutableError):
        run_store.save_run_manifest(run_id, manifest_v1)

    # Reset status
    run_store.update_run_status(run_id, "COMPLETED")

    # 2. Initial save
    p1 = run_store.save_run_manifest(run_id, manifest_v1)
    assert Path(p1).exists()

    # 3. Idempotent save with same digest returns target
    assert run_store.save_run_manifest(run_id, manifest_v1) == p1

    # Corrupt target JSON handling on divergent save creates revision
    Path(p1).write_text("not-valid-json", encoding="utf-8")
    rev_corrupt = run_store.save_run_manifest(run_id, manifest_v1)
    assert "manifest_revisions" in rev_corrupt

    # Restore valid manifest so target has valid JSON
    import json

    Path(p1).write_text(json.dumps(manifest_v1), encoding="utf-8")

    # 4. Save divergent manifest when unsealed creates revision
    manifest_v2 = {"run_id": run_id, "version": "2.0.0"}
    rev_p = run_store.save_run_manifest(run_id, manifest_v2)
    assert "manifest_revisions" in rev_p

    # 5. Save divergent manifest when sealed raises RunManifestImmutableError
    run_store.seal(run_id)
    manifest_v3 = {"run_id": run_id, "version": "3.0.0"}
    with pytest.raises(RunManifestImmutableError):
        run_store.save_run_manifest(run_id, manifest_v3)


def test_commit_certification_branches(
    run_store: LocalFileRunStore, monkeypatch: pytest.MonkeyPatch
):
    """P0-2: Verify commit_certification lease, evidence failure, and immutability branches."""
    run_id = "test-run-commit-branches"
    run_store.create_run(run_id, scenario_id="s1")
    owner = "commit-owner"
    fence = "commit-fence"

    manifest = {"run_id": run_id, "score": 1.0}

    # 1. Without active lease returns False
    assert (
        run_store.commit_certification(
            run_id, manifest=manifest, owner_id=owner, fencing_token=fence
        )
        is False
    )

    # Acquire lease
    assert run_store.acquire_certification_lease(
        run_id, owner_id=owner, fencing_token=fence, timeout_seconds=60.0
    )

    # 1b. Missing run record returns False
    vault = run_store._get_run_vault(run_id)
    (vault / "run_record.json").unlink()
    assert (
        run_store.commit_certification(
            run_id, manifest=manifest, owner_id=owner, fencing_token=fence
        )
        is False
    )
    # Re-create record
    run_store.create_run(run_id, scenario_id="s1")

    # 2. Context mismatch returns False
    assert (
        run_store.commit_certification(
            run_id,
            manifest=manifest,
            owner_id=owner,
            fencing_token=fence,
            context={"tenant": "nonexistent"},
        )
        is False
    )

    # 3. Evidence capture failed returns False
    vault = run_store._get_run_vault(run_id)
    run_store._write_bytes_durable(vault / ".evidence_capture_failed", b"failed\n")
    assert (
        run_store.commit_certification(
            run_id, manifest=manifest, owner_id=owner, fencing_token=fence
        )
        is False
    )

    # Remove evidence failure marker
    (vault / ".evidence_capture_failed").unlink()

    # 4. Commit fails on OSError during journal write
    monkeypatch.setattr(
        run_store,
        "_write_json_durable",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("journal write failed")),
    )
    assert (
        run_store.commit_certification(
            run_id, manifest=manifest, owner_id=owner, fencing_token=fence
        )
        is False
    )
    monkeypatch.undo()

    # 5. Successful commit
    assert (
        run_store.commit_certification(
            run_id, manifest=manifest, owner_id=owner, fencing_token=fence
        )
        is True
    )
    assert run_store._is_sealed(vault)

    # 6. Re-commit when already sealed with matching manifest returns True
    assert (
        run_store.commit_certification(
            run_id, manifest=manifest, owner_id=owner, fencing_token=fence
        )
        is True
    )


def test_reserved_and_dispatched_lifecycle_states_mapped_to_open(
    run_store: LocalFileRunStore,
):
    """Verify get_run_lifecycle_state recognizes RESERVED and DISPATCHED as OPEN states."""
    from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state

    run_id = "test-run-lifecycle-dispatched"
    run_store.reserve_submission(
        run_id=run_id,
        scenario_id="scenario_test",
        agent_id="test_agent",
        metadata={"execution_mode": "live"},
        context={"tenant_id": "test_t"},
        idempotency_key="idemp-123",
    )

    # Immediately after reservation, lifecycle should be OPEN
    assert (
        get_run_lifecycle_state(run_id, run_store=run_store, context={"tenant_id": "test_t"})
        == RunLifecycleState.OPEN
    )

    # Transition to DISPATCHED
    run_store.transition_submission(
        run_id, "RESERVED", "DISPATCHED", context={"tenant_id": "test_t"}
    )
    assert (
        get_run_lifecycle_state(run_id, run_store=run_store, context={"tenant_id": "test_t"})
        == RunLifecycleState.OPEN
    )

    # Transition to RUNNING
    run_store.transition_submission(
        run_id, "DISPATCHED", "RUNNING", context={"tenant_id": "test_t"}
    )
    assert (
        get_run_lifecycle_state(run_id, run_store=run_store, context={"tenant_id": "test_t"})
        == RunLifecycleState.OPEN
    )
