"""
Branch coverage matrix for eval_runner/flight_recorder.py.

Statement and branch coverage for FlightRecorderPlugin,
file handles, cryptographic signing, vault rotation, and trace seals.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin


def test_flight_recorder_init_signing_backends(tmp_path):
    # 1. Custom signing backend provided
    mock_backend = MagicMock()
    fr_custom = FlightRecorderPlugin(log_dir=tmp_path / "logs", signing_backend=mock_backend)
    assert fr_custom.signing_backend == mock_backend

    # 2. Private key path in environment initializes LocalEd25519SigningBackend
    with patch.dict(os.environ, {"FLIGHT_RECORDER_KEY_PATH": "dummy_key_path"}):
        with patch("eval_runner.flight_recorder.LocalEd25519SigningBackend") as mock_ed:
            FlightRecorderPlugin(log_dir=tmp_path / "logs")
            assert mock_ed.called


def test_flight_recorder_require_signing_fail_closed(tmp_path):
    fr = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    event = Event("test_event", {"run_id": "run-req-sign"})

    with patch.dict(os.environ, {"EVAL_REQUIRE_SIGNING": "true"}):
        with pytest.raises(RuntimeError, match="CryptographicSigningError: Signing is mandatory"):
            fr.handle_event(event)


def test_flight_recorder_signing_success_and_failure_modes(tmp_path):
    # 1. Successful signing
    mock_signer = MagicMock()
    mock_signer.sign_payload.return_value = "sig_hex_123"
    fr = FlightRecorderPlugin(log_dir=tmp_path / "logs", signing_backend=mock_signer)
    event = Event("test_event", {"run_id": "run-sign-ok"})
    fr.handle_event(event)
    assert mock_signer.sign_payload.called

    # 2. Signing failure with EVAL_SIGNING_FAIL_CLOSED=true
    mock_failing_signer = MagicMock()
    mock_failing_signer.sign_payload.side_effect = RuntimeError("Crypto hardware error")
    fr_fail = FlightRecorderPlugin(log_dir=tmp_path / "logs", signing_backend=mock_failing_signer)
    event_fail = Event("test_event", {"run_id": "run-sign-err"})

    with patch.dict(os.environ, {"EVAL_SIGNING_FAIL_CLOSED": "true"}):
        with pytest.raises(RuntimeError, match="Failed to sign trace event"):
            fr_fail.handle_event(event_fail)

    # 3. Signing failure with EVAL_SIGNING_FAIL_CLOSED=false (soft-fail with _sig_error)
    with patch.dict(os.environ, {"EVAL_SIGNING_FAIL_CLOSED": "false"}):
        fr_fail.handle_event(event_fail)


def test_flight_recorder_io_modes_and_persistence_fail_closed(tmp_path):
    # 1. Writing directly to per_run_log_path when artifact_store is explicitly None
    fr_no_art = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    fr_no_art.artifact_store = None
    event = Event("test_event", {"run_id": "run-direct-io"})
    fr_no_art.handle_event(event)
    fr_no_art.flush()
    fr_no_art.finalize_run("run-direct-io")

    # 2. Any persistence failure is terminal; no environment opt-in exists.
    fr_err = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    event_err = Event("test_event", {"run_id": "run-io-err"})
    with patch.object(
        fr_err.artifact_store, "store_artifact", side_effect=OSError("Disk write failed")
    ):
        with pytest.raises(
            RuntimeError, match="TracePersistenceError: Failed to persist telemetry"
        ):
            fr_err.handle_event(event_err)


def test_flight_recorder_finalize_run_variations(tmp_path):
    fr = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    run_id = "run-finalize-test"
    event = Event("test_event", {"run_id": run_id})
    fr.handle_event(event)

    # 1. Handle flush exceptions in finalize_run (shutdown race and general error)
    fake_path = str(tmp_path / "logs" / run_id / "run.jsonl")
    mock_handle = MagicMock()
    mock_handle.flush.side_effect = ValueError("I/O on closed file")
    fr._handles[fake_path] = mock_handle
    fr.finalize_run(run_id)

    mock_handle_gen = MagicMock()
    mock_handle_gen.flush.side_effect = RuntimeError("Sync error")
    fr._handles[fake_path] = mock_handle_gen
    fr.finalize_run(run_id)

    # 2. Finalize without specific run_id (closes all handles, handle=None branch)
    fr._handles["global_path"] = MagicMock()
    fr._handles["none_handle"] = None
    fr.finalize_run(None)

    # 3. Artifact store fallback to disk when get_artifact raises or returns empty
    mock_art_store = MagicMock()
    mock_art_store.get_artifact.side_effect = Exception("Not in store")
    fr_disk = FlightRecorderPlugin(log_dir=tmp_path / "logs", artifact_store=mock_art_store)
    # Write a real file on disk
    run_disk_dir = tmp_path / "logs" / "run-disk-fallback"
    run_disk_dir.mkdir(parents=True, exist_ok=True)
    (run_disk_dir / "run.jsonl").write_text('{"event":"disk"}\n', encoding="utf-8")

    # Mock get_default_signer with create=True
    mock_signer = MagicMock()
    mock_signer.sign.return_value = b"signed_seal_bytes"
    mock_signer.identity = "test-authority"
    with patch("eval_runner.identity.get_default_signer", return_value=mock_signer, create=True):
        fr_disk.finalize_run("run-disk-fallback")
        assert mock_art_store.store_artifact.called

    # 4. Seal storing failure exception handling
    mock_art_store.store_artifact.side_effect = Exception("Store seal error")
    fr_disk.finalize_run("run-disk-fallback")

    # 5. Signer is None in get_default_signer
    mock_art_store.store_artifact.side_effect = None
    with patch("eval_runner.identity.get_default_signer", return_value=None, create=True):
        fr_disk.finalize_run("run-disk-fallback")


def test_flight_recorder_after_evaluation_and_rotation(tmp_path):
    fr = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    context = MagicMock()
    context.run_id = "run-after-eval"

    fr.after_evaluation(context, [])

    # Finalize with None run_id
    fr.finalize_run(None)

    # Flush error handling
    mock_bad_handle = MagicMock()
    mock_bad_handle.flush.side_effect = OSError("Flush fail")
    fr._handles["bad_h"] = mock_bad_handle
    fr.flush()

    # Vault rotation with count and cleanup
    v1 = tmp_path / "logs" / "v1"
    v2 = tmp_path / "logs" / "v2"
    v3 = tmp_path / "logs" / "v3"
    v1.mkdir(parents=True, exist_ok=True)
    v2.mkdir(parents=True, exist_ok=True)
    v3.mkdir(parents=True, exist_ok=True)
    fr.log_rotate_count = 2
    fr.rotate_logs(is_new_run=True)

    # Vault rotation when targets <= effective_count
    fr.log_rotate_count = 10
    fr.rotate_logs(is_new_run=False)


def test_flight_recorder_fail_closed_in_certification_mode(tmp_path):
    """Persistence failure in certification mode transitions run to CERTIFICATION_FAILED

    and unconditionally forbids seal or certificate generation.
    """
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs", certification_mode=True)
    run_id = "cert-run-001"

    with patch("builtins.open", side_effect=OSError("Disk full / write failure")):
        event = Event("model_call", {"run_id": run_id, "prompt": "test"})
        with pytest.raises(RuntimeError, match="TracePersistenceError"):
            recorder.handle_event(event)

    assert recorder.get_run_state(run_id) == "CERTIFICATION_FAILED"
    assert run_id in recorder._failed_runs

    with pytest.raises(RuntimeError, match="TracePersistenceError"):
        recorder.finalize_run(run_id)

    seal_file = tmp_path / "logs" / run_id / "trace_seal.json"
    assert not seal_file.exists()


def test_flight_recorder_env_certification_mode(monkeypatch, tmp_path):
    """EVAL_CERTIFICATION_MODE=true or EVAL_ATTESTATION_MODE=true activates fail-closed."""
    monkeypatch.setenv("EVAL_CERTIFICATION_MODE", "true")
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    assert recorder.is_certification_mode() is True

    run_id = "cert-env-run"
    with patch("builtins.open", side_effect=OSError("Storage failure")):
        event = Event("step_start", {"run_id": run_id})
        with pytest.raises(RuntimeError, match="TracePersistenceError"):
            recorder.handle_event(event)

    assert recorder.get_run_state(run_id) == "CERTIFICATION_FAILED"


def test_flight_recorder_run_start_collisions_and_unknown_run(tmp_path):
    from eval_runner.events import CoreEvents

    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs")

    # 1. RUN_START with unknown run_id proceeds without collision check
    ev_unknown = Event(CoreEvents.RUN_START, {"run_id": "unknown"})
    recorder.handle_event(ev_unknown)

    # 2. RUN_START with colliding existing run vault directory
    run_id = "colliding_run"
    colliding_dir = tmp_path / "logs" / run_id
    colliding_dir.mkdir(parents=True, exist_ok=True)
    ev_collide = Event(CoreEvents.RUN_START, {"run_id": run_id})
    with pytest.raises(RuntimeError, match="RunIdCollision"):
        recorder.handle_event(ev_collide)


def test_flight_recorder_handle_event_rejected_states_and_write_assertions(tmp_path):
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    run_id = "state_rejection_run"

    # 1. Rejected write when run is in FINALIZING or SEALED state
    recorder._run_states[run_id] = "FINALIZING"
    ev = Event("step_event", {"run_id": run_id})
    recorder.handle_event(ev)
    assert not (tmp_path / "logs" / run_id / "run.jsonl").exists()

    recorder._run_states[run_id] = "SEALED"
    recorder.handle_event(ev)
    assert not (tmp_path / "logs" / run_id / "run.jsonl").exists()

    # 2. Trace write assertion failure
    recorder._run_states[run_id] = "RUNNING"
    with patch(
        "eval_runner.run_lifecycle.assert_can_write_trace",
        side_effect=PermissionError("Lifecycle lock immutable"),
    ):
        with pytest.raises(
            RuntimeError, match="TracePersistenceError: Run '.*' cannot accept trace writes"
        ):
            recorder.handle_event(ev)

    # 3. Handle event with unknown run_id writes to master log
    ev_unknown = Event("global_event", {"data": "test"})
    recorder.handle_event(ev_unknown)


def test_flight_recorder_sequence_scanning_and_error_handling(tmp_path):
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    run_id = "seq_scan_run"
    run_dir = tmp_path / "logs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    target_trace = run_dir / "run.jsonl"

    # Pre-populate trace with valid sequence, blank line, invalid JSON,
    # non-int sequence, lower sequence, and higher sequence
    target_trace.write_text(
        '{"event": "start", "_seq": 3}\n'
        "\n"
        "not_json_line\n"
        '{"event": "step", "_seq": "not_int"}\n'
        '{"event": "step", "_seq": 1}\n'
        '{"event": "step", "_seq": 7}\n',
        encoding="utf-8",
    )

    ev = Event("new_step", {"run_id": run_id})
    recorder.handle_event(ev)
    assert recorder._sequence_numbers[run_id] == 8

    # Sequence scan when opening target trace raises error
    run_err = "seq_scan_err"
    run_err_dir = tmp_path / "logs" / run_err
    run_err_dir.mkdir(parents=True, exist_ok=True)
    (run_err_dir / "run.jsonl").write_text('{"event": "start"}\n', encoding="utf-8")

    real_open = open

    def mock_open_scan(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if mode == "r" and str(path).endswith("run.jsonl") and run_err in str(path):
            raise OSError("Read scan disk error")
        return real_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open_scan):
        recorder.handle_event(Event("err_step", {"run_id": run_err}))
        assert recorder._sequence_numbers[run_err] == 1


def test_flight_recorder_io_error_with_unknown_run_id(tmp_path):
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    recorder.artifact_store = None

    real_open = open

    def mock_open_err(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if "a" in mode:
            raise OSError("Disk failure")
        return real_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open_err):
        with pytest.raises(
            RuntimeError, match="TracePersistenceError: Failed to persist telemetry"
        ):
            recorder.handle_event(Event("anon_event", {"run_id": "unknown"}))


def test_flight_recorder_finalize_run_lifecycle_and_sealing_exceptions(tmp_path):
    from eval_runner.run_lifecycle import RunLifecycleState

    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs", certification_mode=True)
    run_id = "finalize_exc_run"

    # Write one event
    recorder.handle_event(Event("step", {"run_id": run_id}))

    # 1. Lifecycle transition to FINALIZING fails
    with patch(
        "eval_runner.run_lifecycle.transition_run_lifecycle",
        side_effect=RuntimeError("State transition rejected"),
    ):
        with pytest.raises(RuntimeError, match="failed to persist FINALIZING lifecycle transition"):
            recorder.finalize_run(run_id)

    assert recorder.get_run_state(run_id) == "CERTIFICATION_FAILED"

    # Reset run state for further branch testing
    recorder._failed_runs.discard(run_id)
    recorder._run_states[run_id] = "RUNNING"

    # 2. Certification mode with null signer raises RuntimeError
    with patch("eval_runner.identity.get_default_signer", return_value=None):
        with pytest.raises(RuntimeError, match="requires a non-null cryptographic signer"):
            recorder.finalize_run(run_id)

    # 3. Signer with get_key_id() method and existing non-null backend
    recorder._failed_runs.discard(run_id)
    recorder._run_states[run_id] = "RUNNING"

    class CustomSigner:
        identity = "custom_auth"

        def get_key_id(self):
            return "key_id_999"

        def sign(self, payload):
            return b"custom_signature"

    mock_signer = CustomSigner()
    recorder.signing_backend = mock_signer
    recorder.finalize_run(run_id)
    assert recorder.get_run_state(run_id) == "SEALED"

    # 4. Signer failure in certification mode
    run_sign_fail = "run_sign_fail"
    recorder._run_states[run_sign_fail] = "RUNNING"
    failing_signer = MagicMock()
    failing_signer.identity = "failing_auth"
    failing_signer.key_id = "key_1"
    failing_signer.sign.side_effect = RuntimeError("HSM unreachable")

    recorder.signing_backend = failing_signer
    with pytest.raises(RuntimeError, match="Cryptographic trace seal signing failed"):
        recorder.finalize_run(run_sign_fail)
    assert recorder.get_run_state(run_sign_fail) == "CERTIFICATION_FAILED"

    # 5. Artifact store error in certification mode
    run_art_fail = "run_art_fail"
    recorder._run_states[run_art_fail] = "RUNNING"
    recorder.signing_backend = mock_signer
    with patch.object(
        recorder.artifact_store, "store_artifact", side_effect=OSError("Store seal error")
    ):
        with pytest.raises(OSError, match="Store seal error"):
            recorder.finalize_run(run_art_fail)
        assert recorder.get_run_state(run_art_fail) == "CERTIFICATION_FAILED"

    # 6. SEALED lifecycle transition failure
    run_seal_fail = "run_seal_fail"
    recorder._run_states[run_seal_fail] = "RUNNING"

    def mock_transition(r_id, target_state, **kwargs):
        if target_state == RunLifecycleState.SEALED:
            raise RuntimeError("Cannot transition to SEALED")

    with patch("eval_runner.run_lifecycle.transition_run_lifecycle", side_effect=mock_transition):
        with pytest.raises(RuntimeError, match="failed to persist SEALED lifecycle transition"):
            recorder.finalize_run(run_seal_fail)
        assert recorder.get_run_state(run_seal_fail) == "CERTIFICATION_FAILED"

    # 7. Non-certification mode soft failure for signer
    run_soft = "run_soft_sign"
    failing_signer.sign_payload.return_value = "hex_sig_payload"
    recorder_soft = FlightRecorderPlugin(log_dir=tmp_path / "logs", certification_mode=False)
    recorder_soft.handle_event(Event("step", {"run_id": run_soft}))
    recorder_soft.signing_backend = failing_signer
    recorder_soft.finalize_run(run_soft)

    # 8. Non-certification mode soft failure for artifact store and skipping SEALED if failed
    run_soft_art = "run_soft_art"
    recorder_soft.handle_event(Event("step", {"run_id": run_soft_art}))
    recorder_soft.signing_backend = mock_signer

    def mock_store_soft(*args, **kwargs):
        recorder_soft._run_states[run_soft_art] = "CERTIFICATION_FAILED"
        raise OSError("Store seal error")

    with patch.object(recorder_soft.artifact_store, "store_artifact", side_effect=mock_store_soft):
        recorder_soft.finalize_run(run_soft_art)

    # 9. Pre-failed run in finalize_run
    run_prefailed = "run_prefailed"
    recorder_soft._run_states[run_prefailed] = "CERTIFICATION_FAILED"
    with pytest.raises(RuntimeError, match="cannot produce trace seal"):
        recorder_soft.finalize_run(run_prefailed)


def test_flight_recorder_freeze_run(tmp_path):
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs")

    # 1. No-op for empty or unknown run_id
    recorder.freeze_run(None)
    recorder.freeze_run("unknown")

    # 2. Normal freeze_run
    run_id = "run_freeze_ok"
    recorder.handle_event(Event("start", {"run_id": run_id}))
    recorder.freeze_run(run_id)
    assert recorder.get_run_state(run_id) == "SEALED"

    # 3. Transition to FINALIZING failure in freeze_run
    run_err = "run_freeze_err"
    recorder._run_states[run_err] = "RUNNING"
    with patch(
        "eval_runner.run_lifecycle.transition_run_lifecycle",
        side_effect=RuntimeError("Cannot finalize"),
    ):
        with pytest.raises(RuntimeError, match="failed to persist FINALIZING lifecycle transition"):
            recorder.freeze_run(run_err)
        assert recorder.get_run_state(run_err) == "CERTIFICATION_FAILED"


def test_flight_recorder_close_execution_writes_variations(tmp_path):
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    run_id = "run_close_writes"

    recorder.handle_event(Event("step", {"run_id": run_id}))

    # 1. Close execution writes when handle entry is None
    target_path = str(tmp_path / "logs" / run_id / "run.jsonl")
    recorder._handles[target_path] = None
    recorder.close_execution_writes(run_id)

    # 2. Close execution writes with exception
    mock_bad_handle = MagicMock()
    mock_bad_handle.flush.side_effect = OSError("Flush failed on close")
    recorder._handles[target_path] = mock_bad_handle
    with pytest.raises(RuntimeError, match="TracePersistenceError: failed closing execution trace"):
        recorder.close_execution_writes(run_id)
    assert recorder.get_run_state(run_id) == "CERTIFICATION_FAILED"

    # 3. Close execution writes with exception on unknown run_id
    recorder._handles["unknown_path"] = mock_bad_handle
    with pytest.raises(RuntimeError, match="TracePersistenceError: failed closing execution trace"):
        recorder.close_execution_writes("unknown")
