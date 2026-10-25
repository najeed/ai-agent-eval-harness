from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.run_lifecycle import RunLifecycleState, transition_run_lifecycle


def test_resume_sequence_comes_from_provider_events(tmp_path):
    store = LocalFileRunStore(tmp_path / "provider")
    store.append_events("resume", [{"event": "prior", "_seq": 7}])
    recorder = FlightRecorderPlugin(run_store=store)

    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": "resume", "is_resume": True}))
    recorder.handle_event(Event("step", {"run_id": "resume"}))

    assert store.get_events("resume", offset=0, limit=100)[-1]["_seq"] == 9


def test_recorder_rejects_lifecycle_closed_by_provider(tmp_path):
    store = LocalFileRunStore(tmp_path / "provider")
    store.create_run("sealed", scenario_id="scenario")
    transition_run_lifecycle("sealed", RunLifecycleState.FINALIZING, run_store=store)
    recorder = FlightRecorderPlugin(run_store=store)

    with pytest.raises(RuntimeError, match="cannot accept trace writes"):
        recorder.handle_event(Event("step", {"run_id": "sealed"}))


def test_finalize_transitions_bound_provider(tmp_path):
    store = LocalFileRunStore(tmp_path / "provider")
    recorder = FlightRecorderPlugin(run_store=store)
    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": "finalize"}))

    recorder.finalize_run("finalize")

    assert store.get_run("finalize")["lifecycle"] == "FINALIZING"


def test_init_log_dir_and_signing_backend_variants(tmp_path, monkeypatch):
    # 1. log_dir provided sets up local run_store and artifact_store
    rec1 = FlightRecorderPlugin(log_dir=tmp_path / "custom_log_dir")
    assert rec1._default_run_store is not None
    assert rec1.artifact_store is not None

    # 2. resolve_run_store failure handled cleanly in init
    with patch(
        "eval_runner.runtime_services.resolve_run_store", side_effect=RuntimeError("no store")
    ):
        rec2 = FlightRecorderPlugin()
        assert rec2._default_run_store is None

    # 3. FLIGHT_RECORDER_KEY_PATH provided instantiates LocalEd25519SigningBackend
    fake_key = tmp_path / "test.key"
    fake_key.write_bytes(b"x" * 32)
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(fake_key))
    with patch("eval_runner.flight_recorder.LocalEd25519SigningBackend"):
        rec3 = FlightRecorderPlugin()
        assert rec3.signing_backend is not None


def test_bind_and_release_run_provider_edge_cases(tmp_path):
    store_a = LocalFileRunStore(tmp_path / "store-a")
    store_b = LocalFileRunStore(tmp_path / "store-b")
    rec = FlightRecorderPlugin()

    # 1. Empty or unknown run_id or None run_store
    rec.bind_run_provider("", store_a)
    rec.bind_run_provider("unknown", store_a)
    rec.bind_run_provider("r1", None)
    assert "r1" not in rec._run_providers

    # 2. Valid binding and context update
    rec.bind_run_provider("r1", store_a, context={"tenant": "t1"})
    assert rec._run_providers["r1"][1] == {"tenant": "t1"}
    rec.bind_run_provider("r1", store_a, context={"env": "prod"})
    assert rec._run_providers["r1"][1] == {"tenant": "t1", "env": "prod"}

    # 3. Provider affinity violation
    with pytest.raises(RuntimeError, match="RunStorageProviderAffinityViolation"):
        rec.bind_run_provider("r1", store_b)

    # 4. Release run provider
    rec.release_run_provider("r1")
    assert "r1" not in rec._run_providers

    # 5. Classmethods bind_active_recorder and release_active_recorder
    FlightRecorderPlugin.bind_active_recorder("r2", store_a, context={"c": 1})
    rec_in_bus = next(
        sub.__self__
        for sub in __import__("eval_runner.events", fromlist=["EventEmitter"])
        .EventEmitter.get_global()
        ._subscribers
        if isinstance(getattr(sub, "__self__", None), FlightRecorderPlugin)
    )
    assert "r2" in rec_in_bus._run_providers

    # release with non-matching store does not release
    FlightRecorderPlugin.release_active_recorder("r2", run_store=store_b)
    assert "r2" in rec_in_bus._run_providers

    # release with matching store or None releases
    FlightRecorderPlugin.release_active_recorder("r2", run_store=store_a)
    assert "r2" not in rec_in_bus._run_providers

    # release when binding is None safely continues
    FlightRecorderPlugin.release_active_recorder("r_missing", run_store=store_a)


def test_handle_event_run_id_collisions_and_resumption_errors(tmp_path):
    store = LocalFileRunStore(tmp_path / "store")
    rec = FlightRecorderPlugin(run_store=store)

    # 1. RUN_START when lifecycle is already FINALIZING/SEALED -> RunIdCollision
    store.create_run("run-coll", "scenario")
    transition_run_lifecycle("run-coll", RunLifecycleState.FINALIZING, run_store=store)
    with pytest.raises(RuntimeError, match="RunIdCollision"):
        rec.handle_event(Event(CoreEvents.RUN_START, {"run_id": "run-coll", "is_resume": False}))

    # 2. is_resume=True when lifecycle is in FINALIZING/SEALED -> ResumptionError
    with pytest.raises(RuntimeError, match="ResumptionError"):
        rec.handle_event(Event(CoreEvents.RUN_START, {"run_id": "run-coll", "is_resume": True}))

    # 3. Event when run_state in ("FINALIZING", "SEALED") is rejected and returns early
    rec._run_states["run-closed"] = "SEALED"
    # Should not raise, just logs debug and returns early
    rec.handle_event(Event("step", {"run_id": "run-closed"}))


def test_handle_event_unowned_and_signing_failures(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path / "store")
    rec = FlightRecorderPlugin(run_store=store)

    # 1. Unowned event (no run_id) raises TracePersistenceError
    with pytest.raises(
        RuntimeError, match="TracePersistenceError: trace event has no run ownership"
    ):
        rec.handle_event(Event("step", {"data": "no_run_id"}))

    # 2. EVAL_REQUIRE_SIGNING=true with NullSigningBackend raises CryptographicSigningError
    monkeypatch.setenv("EVAL_REQUIRE_SIGNING", "true")
    with pytest.raises(RuntimeError, match="CryptographicSigningError: Signing is mandatory"):
        rec.handle_event(Event("step", {"run_id": "run-sign-req"}))
    monkeypatch.delenv("EVAL_REQUIRE_SIGNING")

    # 3. Signing failure under AUDIT_LEVEL=2 raises CryptographicSigningError
    mock_signer = MagicMock()
    mock_signer.can_sign.return_value = True
    mock_signer.sign_payload.side_effect = RuntimeError("Signature calculation failed")
    rec_fail_sign = FlightRecorderPlugin(run_store=store, signing_backend=mock_signer)
    with pytest.raises(RuntimeError, match="CryptographicSigningError: Failed to sign trace event"):
        rec_fail_sign.handle_event(Event("step", {"run_id": "run-sign-fail"}))


def test_finalize_run_edge_cases_and_seals(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path / "store")
    store.create_run("run-failed-state", "scenario")
    rec = FlightRecorderPlugin(run_store=store)

    # 1. finalize_run without run_id returns early
    rec.finalize_run(None)
    rec.finalize_run("")

    # 2. finalize_run on failed run raises TracePersistenceError
    rec._failed_runs.add("run-failed-state")
    with pytest.raises(
        RuntimeError, match="CERTIFICATION_FAILED due to telemetry persistence failure"
    ):
        rec.finalize_run("run-failed-state")

    # 3. AES_CERTIFICATION_MODE=1 with NullSigningBackend raises RuntimeError
    rec._failed_runs.clear()
    rec._run_states.clear()
    monkeypatch.setenv("AES_CERTIFICATION_MODE", "1")
    with pytest.raises(
        RuntimeError, match="AES_CERTIFICATION_MODE=1 requires a non-null cryptographic signer"
    ):
        rec.finalize_run("run-failed-state")
    monkeypatch.delenv("AES_CERTIFICATION_MODE")

    # 4. finalize_run on already SEALED run sets state and returns
    store.create_run("run-already-sealed", "scenario")
    transition_run_lifecycle("run-already-sealed", RunLifecycleState.FINALIZING, run_store=store)
    transition_run_lifecycle("run-already-sealed", RunLifecycleState.SEALED, run_store=store)
    rec.finalize_run("run-already-sealed")
    assert rec.get_run_state("run-already-sealed") == "SEALED"

    # 5. finalize_run with non-null signer creates trace_seal.json
    # with signer identity and signature
    store.create_run("run-seal-art", "scenario")
    mock_signer = MagicMock()
    mock_signer.identity = "test-node"
    mock_signer.key_id = "key-001"
    mock_signer.sign.return_value = b"\xaa\xbb\xcc"

    mock_art_store = MagicMock()
    rec_art = FlightRecorderPlugin(
        run_store=store,
        signing_backend=mock_signer,
        artifact_store=mock_art_store,
    )
    rec_art.finalize_run("run-seal-art")
    mock_art_store.store_artifact.assert_called_once()
    stored_json = json.loads(mock_art_store.store_artifact.call_args[1]["content"])
    assert stored_json["signer_identity"] == "test-node"
    assert stored_json["key_id"] == "key-001"
    assert stored_json["signature"] == "aabbcc"

    # 6. Artifact store finalize error in certification mode raises exception
    mock_art_fail = MagicMock()
    mock_art_fail.store_artifact.side_effect = OSError("Disk unmounted")
    rec_art_fail = FlightRecorderPlugin(
        run_store=store,
        signing_backend=mock_signer,
        artifact_store=mock_art_fail,
        certification_mode=True,
    )
    store.create_run("run-cert-fail", "scenario")
    with pytest.raises(OSError, match="Disk unmounted"):
        rec_art_fail.finalize_run("run-cert-fail")
    assert rec_art_fail.get_run_state("run-cert-fail") == "CERTIFICATION_FAILED"


def test_freeze_run_and_utility_hooks(tmp_path):
    store = LocalFileRunStore(tmp_path / "store")
    rec = FlightRecorderPlugin(run_store=store)

    # 1. freeze_run on empty / unknown run_id returns early
    rec.freeze_run("")
    rec.freeze_run("unknown")

    # 2. freeze_run success
    store.create_run("run-freeze", "scenario")
    rec.freeze_run("run-freeze")
    assert rec.get_run_state("run-freeze") == "FINALIZING"

    # 3. freeze_run when transition_run_lifecycle fails raises TracePersistenceError
    with patch(
        "eval_runner.run_lifecycle.transition_run_lifecycle",
        side_effect=RuntimeError("transition fail"),
    ):
        with pytest.raises(RuntimeError, match="failed to persist FINALIZING lifecycle transition"):
            rec.freeze_run("run-freeze")

    # 4. Utility hooks
    assert rec.close_execution_writes("r") is None
    rec.on_cleanup_runs()
    rec.after_evaluation(MagicMock(run_id="r"), [])
    assert rec.rotate_logs() is None
    assert rec.flush() is None


def test_flight_recorder_uncovered_branches(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path / "store")
    from eval_runner.events import EventEmitter

    # 1. bind_run_provider with context=None
    rec = FlightRecorderPlugin()
    rec.bind_run_provider("r_no_ctx", store, context=None)
    assert rec._run_providers["r_no_ctx"][1] is None

    # 2. Non-recorder subscriber in EventEmitter._subscribers
    def dummy_listener(_event):
        pass

    bus = EventEmitter.get_global()
    bus._subscribers.append(dummy_listener)
    try:
        FlightRecorderPlugin.bind_active_recorder("r_dummy", store)
        FlightRecorderPlugin.release_active_recorder("r_dummy", run_store=store)
    finally:
        if dummy_listener in bus._subscribers:
            bus._subscribers.remove(dummy_listener)

    # 3. _provider_for_run when _default_run_store is None caches resolved store
    rec_lazy = FlightRecorderPlugin()
    rec_lazy._default_run_store = None
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=store):
        resolved_st, _ = rec_lazy._provider_for_run("r_lazy")
        assert resolved_st is store
        assert rec_lazy._default_run_store is store

    # 4. RUN_START with run_id="unknown"
    rec_unk = FlightRecorderPlugin(run_store=store)
    with pytest.raises(
        RuntimeError, match="TracePersistenceError: trace event has no run ownership"
    ):
        rec_unk.handle_event(Event(CoreEvents.RUN_START, {"data": {"foo": "bar"}}))

    # 5. Event with run_id="unknown" when assert_can_write_trace fails
    with patch(
        "eval_runner.run_lifecycle.assert_can_write_trace",
        side_effect=RuntimeError("Lifecycle locked"),
    ):
        with patch.object(rec_unk, "_provider_for_run", return_value=(store, None)):
            # Calling directly with run_id="" or "unknown"
            with pytest.raises(RuntimeError, match="TracePersistenceError"):
                rec_unk.handle_event(Event("step", {"data": "val"}))

    # 6. Signing failure when EVAL_SIGNING_FAIL_CLOSED="false"
    mock_signer = MagicMock()
    mock_signer.can_sign.return_value = True
    mock_signer.sign_payload.side_effect = RuntimeError("Non-fatal sign error")
    rec_non_fatal = FlightRecorderPlugin(run_store=store, signing_backend=mock_signer)
    monkeypatch.setenv("EVAL_SIGNING_FAIL_CLOSED", "false")
    store.create_run("run-non-fatal", "scenario")
    rec_non_fatal.handle_event(Event("step", {"run_id": "run-non-fatal"}))
    events = store.get_events("run-non-fatal")
    assert events[-1].get("_sig_error") == "Non-fatal sign error"
    monkeypatch.delenv("EVAL_SIGNING_FAIL_CLOSED", raising=False)

    # 7. run_store.append_events fails for known run_id
    rec_append_fail = FlightRecorderPlugin(run_store=store)
    store.create_run("run-append-fail", "scenario")
    with patch.object(store, "append_events", side_effect=OSError("Disk write error")):
        with pytest.raises(RuntimeError, match="Failed to persist telemetry event"):
            rec_append_fail.handle_event(Event("step", {"run_id": "run-append-fail"}))
        assert rec_append_fail.get_run_state("run-append-fail") == "CERTIFICATION_FAILED"

    # 8. finalize_run when artifact_store is None
    store.create_run("run-no-art", "scenario")
    rec_no_art = FlightRecorderPlugin(run_store=store, artifact_store=None)
    rec_no_art.artifact_store = None
    rec_no_art.finalize_run("run-no-art")
    assert rec_no_art.get_run_state("run-no-art") == "FINALIZING"

    # 9. finalize_run with signer having get_key_id(), no key_id, and sign_payload
    store.create_run("run-sig-payload", "scenario")
    mock_art = MagicMock()

    class PayloadSigner:
        identity = "payload-node"

        def can_sign(self):
            return True

        def get_key_id(self):
            return "key-via-getter"

        def sign_payload(self, payload):
            return b"\x12\x34"

    rec_payload = FlightRecorderPlugin(
        run_store=store, signing_backend=PayloadSigner(), artifact_store=mock_art
    )
    rec_payload.finalize_run("run-sig-payload")
    mock_art.store_artifact.assert_called_once()
    envelope = json.loads(mock_art.store_artifact.call_args[1]["content"])
    assert envelope["signer_identity"] == "payload-node"
    assert envelope["signature"] == "1234"
    assert envelope["key_id"] == "key-via-getter"

    # Also test signer where get_key_id returns None
    class NoneKeyIdSigner(PayloadSigner):
        def get_key_id(self):
            return None

    mock_art2 = MagicMock()
    rec_no_key = FlightRecorderPlugin(
        run_store=store, signing_backend=NoneKeyIdSigner(), artifact_store=mock_art2
    )
    store.create_run("run-sig-no-key", "scenario")
    rec_no_key.finalize_run("run-sig-no-key")
    env2 = json.loads(mock_art2.store_artifact.call_args[1]["content"])
    assert "key_id" not in env2

    # 10. finalize_run artifact store error when certification_mode=False
    store.create_run("run-art-ign", "scenario")
    mock_art_ign = MagicMock()
    mock_art_ign.store_artifact.side_effect = OSError("Ignoring artifact error")
    rec_art_ign = FlightRecorderPlugin(
        run_store=store,
        signing_backend=PayloadSigner(),
        artifact_store=mock_art_ign,
        certification_mode=False,
    )
    rec_art_ign.finalize_run("run-art-ign")
    assert rec_art_ign.get_run_state("run-art-ign") == "FINALIZING"
