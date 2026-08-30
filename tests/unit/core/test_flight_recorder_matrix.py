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
    with patch.dict(os.environ, {"EVAL_SIGNING_KEY": "dummy_key_path"}):
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

    # 2. Write error with EVAL_PERSISTENCE_FAIL_CLOSED=true
    fr_err = FlightRecorderPlugin(log_dir=tmp_path / "logs")
    event_err = Event("test_event", {"run_id": "run-io-err"})
    with patch.object(
        fr_err.artifact_store, "store_artifact", side_effect=OSError("Disk write failed")
    ):
        with patch.dict(os.environ, {"EVAL_PERSISTENCE_FAIL_CLOSED": "true"}):
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
