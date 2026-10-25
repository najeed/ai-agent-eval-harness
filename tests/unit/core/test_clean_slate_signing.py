"""
tests/unit/core/test_clean_slate_signing.py
Clean-Slate Signing Backend Capability and Trace Signing Validation.
"""

import json
from pathlib import Path
from typing import Any

from agentv_runtime.discovery import reset_extensions, resolve_extension, set_extension
from agentv_runtime.interfaces import SigningBackend
from eval_runner import config
from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.reference.signing import (
    LocalEd25519SigningBackend,
    NullSigningBackend,
    PQCSigningBackend,
)


class MockExternalKmsSigningBackend(SigningBackend):
    """External KMS backend that implements SigningBackend directly without LocalEd25519."""

    def __init__(self, key_id: str = "kms-key-999"):
        self.key_id = key_id
        self.sign_calls: list[bytes] = []

    def can_sign(self) -> bool:
        return True

    def sign_payload(
        self, payload: bytes, key_identifier: str | Path | Any = None, **kwargs: Any
    ) -> str | dict[str, Any]:
        self.sign_calls.append(payload)
        return f"kms-sig:{self.key_id}"

    def verify_signature(
        self,
        payload: bytes,
        signature: str | dict[str, Any],
        public_key_identifier: str | Path | Any = None,
        **kwargs: Any,
    ) -> bool:
        return str(signature).startswith(f"kms-sig:{self.key_id}")


def test_reference_signing_backends_can_sign():
    """Verify built-in signing backends correctly declare can_sign capability."""
    local_backend = LocalEd25519SigningBackend()
    assert local_backend.can_sign() is True

    null_backend = NullSigningBackend()
    assert null_backend.can_sign() is False

    pqc_backend = PQCSigningBackend()
    # PQC signing requires OQS dependency and loaded private key; unconfigured returns False
    assert pqc_backend.can_sign() is False


def test_external_kms_signing_backend_contract():
    """Verify third-party SigningBackend implementation satisfies capability contract."""
    kms = MockExternalKmsSigningBackend(key_id="vault-key-42")
    assert kms.can_sign() is True

    payload = b"run-step-hash-data"
    signature = kms.sign_payload(payload)
    assert len(kms.sign_calls) == 1
    assert kms.verify_signature(payload, signature) is True


def test_flight_recorder_signs_with_external_kms_backend(tmp_path: Path, monkeypatch):
    """Verify FlightRecorder queries can_sign() and signs trace events using external KMS."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path)
    reset_extensions("run_stores")
    try:
        kms = MockExternalKmsSigningBackend(key_id="test-kms")
        run_store = LocalFileRunStore(tmp_path)
        recorder = FlightRecorderPlugin(
            signing_backend=kms,
            run_store=run_store,
            log_dir=tmp_path,
        )

        run_id = "run-kms-test-001"
        run_store.create_run(run_id, "scen")
        recorder.bind_run_provider(run_id, run_store)
        recorder.handle_event(
            Event(name=CoreEvents.RUN_START, data={"run_id": run_id, "scenario": "scen"})
        )
        recorder.handle_event(
            Event(name=CoreEvents.RUN_END, data={"run_id": run_id, "status": "PASSED"})
        )
        recorder.finalize_run(run_id)

        assert len(kms.sign_calls) >= 1
        trace_path = tmp_path / run_id / "run.jsonl"
        assert trace_path.exists()

        events = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").strip().splitlines()
            if line.strip()
        ]
        signed_events = [e for e in events if e.get("_sig")]
        assert len(signed_events) > 0
        assert signed_events[0]["_sig"] == "kms-sig:test-kms"
    finally:
        reset_extensions("run_stores")


def test_flight_recorder_skips_signing_when_can_sign_false(tmp_path: Path, monkeypatch):
    """Verify FlightRecorder skips event signing when backend declares can_sign() False."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path)
    reset_extensions("run_stores")
    try:
        null_backend = NullSigningBackend()
        run_store = LocalFileRunStore(tmp_path)
        recorder = FlightRecorderPlugin(
            signing_backend=null_backend,
            run_store=run_store,
            log_dir=tmp_path,
        )

        run_id = "run-null-sign-001"
        run_store.create_run(run_id, "scen")
        recorder.bind_run_provider(run_id, run_store)
        recorder.handle_event(
            Event(name=CoreEvents.RUN_START, data={"run_id": run_id, "scenario": "scen"})
        )
        recorder.handle_event(
            Event(name=CoreEvents.RUN_END, data={"run_id": run_id, "status": "PASSED"})
        )
        recorder.finalize_run(run_id)

        trace_path = tmp_path / run_id / "run.jsonl"
        assert trace_path.exists()
        events = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").strip().splitlines()
            if line.strip()
        ]
        for event in events:
            assert "_sig" not in event
    finally:
        reset_extensions("run_stores")


def test_signing_backend_discovery_and_registry_injection():
    """Verify resolve_extension and set_extension operate on signing_backends family."""
    reset_extensions("signing_backends")
    try:
        custom_kms = MockExternalKmsSigningBackend(key_id="registry-key")
        set_extension("signing_backends", custom_kms)

        resolved = resolve_extension(
            "signing_backends",
            default_factory=LocalEd25519SigningBackend,
        )
        assert resolved is custom_kms
        assert resolved.can_sign() is True
    finally:
        reset_extensions("signing_backends")


def test_local_ed25519_signing_and_verification_matrix(tmp_path: Path):
    """Verify LocalEd25519SigningBackend across file paths, PEM strings, bytes, and errors."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

    backend = LocalEd25519SigningBackend()
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = priv.public_key()
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    key_file = tmp_path / "ed25519.pem"
    key_file.write_bytes(priv_pem)
    pub_file = tmp_path / "ed25519_pub.pem"
    pub_file.write_bytes(pub_pem)

    payload = b"canonical-evidence-data"

    # 1. Sign via Path
    sig_hex_file = backend.sign_payload(payload, key_file)
    assert isinstance(sig_hex_file, str)
    assert backend.verify_signature(payload, sig_hex_file, pub_file) is True

    # 2. Sign via PEM string
    sig_hex_str = backend.sign_payload(payload, priv_pem.decode("utf-8"))
    assert backend.verify_signature(payload, sig_hex_str, pub_pem.decode("utf-8")) is True

    # 3. Sign via raw bytes
    sig_hex_bytes = backend.sign_payload(payload, priv_pem)
    assert backend.verify_signature(payload, sig_hex_bytes, pub_pem) is True

    # 4. Verification failure with corrupted signature or mismatched payload
    assert backend.verify_signature(b"wrong-payload", sig_hex_bytes, pub_pem) is False
    assert backend.verify_signature(payload, "deadbeef", pub_pem) is False

    # 5. Invalid key type errors
    import pytest

    with pytest.raises(FileNotFoundError):
        backend.sign_payload(payload, tmp_path / "nonexistent.pem")

    with pytest.raises(TypeError, match="Expected file path, PEM string, or bytes"):
        backend.sign_payload(payload, 12345)

    # Non-Ed25519 private key rejection
    rsa_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_pem = rsa_priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    rsa_pub_pem = rsa_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(TypeError, match="Expected Ed25519PrivateKey"):
        backend.sign_payload(payload, rsa_pem)

    # Non-Ed25519 public key returns False
    assert backend.verify_signature(payload, sig_hex_bytes, rsa_pub_pem) is False
    assert backend.verify_signature(payload, sig_hex_bytes, b"corrupted-pem-data") is False

    # Custom object implementing __bytes__
    class CustomBytes:
        def __bytes__(self):
            return pub_pem

    assert backend.verify_signature(payload, sig_hex_bytes, CustomBytes()) is True

    # Non-existent Path directly returns False
    fake_path = Path("does_not_exist_normally.pem")
    assert backend.verify_signature(payload, sig_hex_bytes, fake_path) is False

    # Path string and Path object triggering OSError during path existence check
    from unittest.mock import patch

    with patch("pathlib.Path.exists", side_effect=OSError("Disk failure")):
        assert backend.verify_signature(payload, sig_hex_bytes, pub_pem.decode("utf-8")) is True
        assert backend.verify_signature(payload, sig_hex_bytes, Path("test_key.pem")) is False


def test_null_signing_backend_methods():
    """Verify NullSigningBackend satisfies SigningBackend protocol with inert defaults."""
    backend = NullSigningBackend()
    assert backend.can_sign() is False
    assert backend.sign_payload(b"data", "key") == ""
    assert backend.verify_signature(b"data", "sig", "key") is False


def test_pqc_signing_backend_branches(monkeypatch):
    """Verify PQCSigningBackend error modes and client integration branches."""
    from unittest.mock import MagicMock

    import pytest

    from eval_runner.identity import IdentityService

    backend = PQCSigningBackend()

    # 1. When PQC client is unavailable
    monkeypatch.setattr(IdentityService, "get_pqc_client", lambda: None)
    assert backend.can_sign() is False

    with pytest.raises(RuntimeError, match="PQC client is not available"):
        backend.sign_payload(b"data")

    # verify_signature with strict mode disabled
    monkeypatch.setattr(config, "PQC_STRICT_MODE", False)
    assert backend.verify_signature(b"data", "sig") is False

    # verify_signature with strict mode enabled
    monkeypatch.setattr(config, "PQC_STRICT_MODE", True)
    with pytest.raises(ValueError, match="PQC_STRICT_MODE Violation"):
        backend.verify_signature(b"data", "sig")

    # 2. When PQC client is active
    mock_client = MagicMock()
    mock_client.sign_digest.return_value = "pqc-sig-123"
    mock_client.verify_digest.return_value = True
    monkeypatch.setattr(IdentityService, "get_pqc_client", lambda: mock_client)

    assert backend.can_sign() is True
    assert backend.sign_payload(b"evidence", key_identifier="custom-pqc-id") == "pqc-sig-123"
    assert (
        backend.verify_signature(b"evidence", "pqc-sig-123", public_key_identifier="custom-pqc-id")
        is True
    )
