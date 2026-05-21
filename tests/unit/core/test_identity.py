import pytest

from eval_runner import config
from eval_runner.identity import IdentityService


def test_identity_service_key_generation(tmp_path):
    """Verify that IdentityService auto-generates keys in the trust root."""
    # Override TRUST_ROOT for test isolation
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / ".aes" / "trust"

    try:
        identity_id = "test_agent_007"
        private_key = IdentityService.get_private_key(identity_id)

        assert private_key is not None

        # Verify physical files exist
        id_dir = config.TRUST_ROOT / identity_id
        assert id_dir.exists()
        assert (id_dir / "private_key.pem").exists()
        assert (id_dir / "public_key.pem").exists()

        # Verify public key resolution
        public_key = IdentityService.get_public_key(identity_id)
        assert public_key is not None

    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_path_security(tmp_path):
    """Verify that IdentityService prevents path traversal outside TRUST_ROOT."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    try:
        with pytest.raises(PermissionError):
            # Attempt to use a traversal ID
            IdentityService.get_private_key("../secret_id")
        with pytest.raises(PermissionError):
            # Attempt to use a traversal ID for public key
            IdentityService.get_public_key("../secret_id")
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_determinism(tmp_path):
    """Verify that IdentityService returns the same key for the same ID."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    try:
        id_1 = "id_v1"
        key_1a = IdentityService.get_private_key(id_1)
        key_1b = IdentityService.get_private_key(id_1)

        # We can't compare the key objects directly (they are fresh objects),
        # but we can compare the bytes.
        from cryptography.hazmat.primitives import serialization

        bytes_a = key_1a.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        bytes_b = key_1b.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        assert bytes_a == bytes_b
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_get_pqc_client(monkeypatch):
    """Verify get_pqc_client coverage scenarios."""
    # 1. PQC disabled
    monkeypatch.setattr(config, "PQC_ENABLED", False)
    IdentityService._pqc_client = None
    assert IdentityService.get_pqc_client() is None

    # 2. Cached client return
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    mock_client = object()
    IdentityService._pqc_client = mock_client
    assert IdentityService.get_pqc_client() is mock_client

    # Reset cache
    IdentityService._pqc_client = None

    # 3. Unsupported PQC provider
    monkeypatch.setattr(config, "PQC_PROVIDER", "invalid_provider")
    assert IdentityService.get_pqc_client() is None

    # 4. ImportError path (cyclecore_pq not found)
    monkeypatch.setattr(config, "PQC_PROVIDER", "cyclecore")
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if "cyclecore_pq" in name:
            raise ImportError("Mocked import error")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    assert IdentityService.get_pqc_client() is None


def test_identity_service_pqc_client_success(monkeypatch):
    """Verify get_pqc_client success path, sign_digest and verify_digest."""
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_PROVIDER", "cyclecore")
    monkeypatch.setattr(config, "CYCLECORE_API_KEY", "dummy_key")
    IdentityService._pqc_client = None

    import base64
    import sys
    import types
    from unittest.mock import MagicMock

    mock_client_instance = MagicMock()
    mock_sign_result = MagicMock()
    mock_sign_result.signature = "pqc_signature_val"
    mock_client_instance.sign.return_value = mock_sign_result

    mock_verify_result = MagicMock()
    mock_verify_result.valid = True
    mock_client_instance.verify.return_value = mock_verify_result

    mock_client_class = MagicMock(return_value=mock_client_instance)

    module = types.ModuleType("cyclecore_pq.client")
    module.CycleCoreClient = mock_client_class

    orig_module = sys.modules.get("cyclecore_pq.client")
    sys.modules["cyclecore_pq.client"] = module
    try:
        client = IdentityService.get_pqc_client()
        assert client is mock_client_instance

        # Test sign_digest
        digest = b"some_digest_bytes"
        sig_str = client.sign_digest(digest)
        assert sig_str == "pqc_signature_val"
        mock_client_instance.sign.assert_called_with(digest)

        # Test verify_digest: signature as string (base64)
        sig_base64 = base64.b64encode(b"a" * 100).decode("latin-1")
        assert client.verify_digest(sig_base64, digest) is True

        # Test verify_digest: signature as string (hex)
        sig_hex = "abcdef" * 40
        assert client.verify_digest(sig_hex, digest) is True

        # Test verify_digest: signature as string fallback
        assert client.verify_digest("short_sig", digest) is True

        # Test verify_digest: signature as bytes
        assert client.verify_digest(b"bytes_signature", digest) is True

        # Test verify_digest exception flow
        mock_client_instance.verify.side_effect = Exception("verify crash")
        assert client.verify_digest(b"sig", digest) is False

    finally:
        if orig_module:
            sys.modules["cyclecore_pq.client"] = orig_module
        else:
            sys.modules.pop("cyclecore_pq.client", None)


def test_identity_service_pqc_client_init_exception(monkeypatch):
    """Verify get_pqc_client failure handling when initialization raises an exception."""
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_PROVIDER", "cyclecore")
    IdentityService._pqc_client = None

    import sys
    import types
    from unittest.mock import MagicMock

    mock_client_class = MagicMock(side_effect=Exception("client init fail"))
    module = types.ModuleType("cyclecore_pq.client")
    module.CycleCoreClient = mock_client_class

    orig_module = sys.modules.get("cyclecore_pq.client")
    sys.modules["cyclecore_pq.client"] = module
    try:
        assert IdentityService.get_pqc_client() is None
    finally:
        if orig_module:
            sys.modules["cyclecore_pq.client"] = orig_module
        else:
            sys.modules.pop("cyclecore_pq.client", None)


def test_identity_service_env_var_key(tmp_path, monkeypatch):
    """Verify resolving private key from environment variables."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"
    IdentityService._pqc_client = None

    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        private_key = ed25519.Ed25519PrivateKey.generate()
        pem_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        identity_id = "env_agent"
        env_var = f"AES_PRIVATE_KEY_{identity_id.upper()}"
        monkeypatch.setenv(env_var, pem_bytes.decode())

        resolved_key = IdentityService.get_private_key(identity_id)
        assert resolved_key is not None

        monkeypatch.setenv(env_var, "INVALID_PEM_CONTENT")
        resolved_fallback = IdentityService.get_private_key(identity_id)
        assert resolved_fallback is not None
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_path_jail_value_error(tmp_path):
    """Verify path traversal raises PermissionError when value/attribute errors happen."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    from unittest.mock import patch

    try:
        with patch("pathlib.Path.is_relative_to", side_effect=ValueError("different drives")):
            with pytest.raises(PermissionError) as exc_info:
                IdentityService.get_private_key("some_id")
            assert "Security violation" in str(exc_info.value)

            with pytest.raises(PermissionError) as exc_info:
                IdentityService.get_public_key("some_id")
            assert "Security violation" in str(exc_info.value)
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_corrupt_private_key(tmp_path):
    """Verify file load exception handles corrupted private key correctly."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    try:
        identity_id = "corrupt_id"
        id_dir = config.TRUST_ROOT / identity_id
        id_dir.mkdir(parents=True, exist_ok=True)
        key_path = id_dir / "private_key.pem"

        with open(key_path, "wb") as f:
            f.write(b"NOT_A_VALID_PEM_KEY")

        with pytest.raises(ValueError):
            IdentityService.get_private_key(identity_id)
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_system_id_provisioning_gate(tmp_path, monkeypatch):
    """Verify auto-provisioning for system_id can be disabled by config."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    monkeypatch.setattr(config, "ALLOW_SYSTEM_IDENTITY_PROVISIONING", False)

    try:
        with pytest.raises(PermissionError) as exc_info:
            IdentityService.get_private_key("system_id")
        msg = "Security Policy Violation: Auto-provisioning for 'system_id' is disabled"
        assert msg in str(exc_info.value)
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_no_auto_provision(tmp_path):
    """Verify auto_provision=False returns None if private/public keys are missing."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    try:
        assert IdentityService.get_private_key("missing_id", auto_provision=False) is None
        assert IdentityService.get_public_key("missing_id", auto_provision=False) is None

        # Test auto_provision=True to cover line 192
        pub_key = IdentityService.get_public_key("missing_id_auto", auto_provision=True)
        assert pub_key is not None
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_public_key_derivation_fallback(tmp_path):
    """Verify public key derivation fallback from private key."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    from cryptography.hazmat.primitives import serialization

    try:
        identity_id = "derive_fallback_agent"
        priv = IdentityService._provision_local_identity(identity_id)

        pub_path = config.TRUST_ROOT / identity_id / "public_key.pem"
        if pub_path.exists():
            pub_path.unlink()

        pub_derived = IdentityService.get_public_key(identity_id, auto_provision=False)
        assert pub_derived is not None

        assert pub_derived.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ) == priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_public_key_derivation_exception(tmp_path):
    """Verify that if private key derivation fails, get_public_key falls back gracefully."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    try:
        identity_id = "deriv_fail"
        id_dir = config.TRUST_ROOT / identity_id
        id_dir.mkdir(parents=True, exist_ok=True)

        with open(id_dir / "private_key.pem", "wb") as f:
            f.write(b"CORRUPT")

        assert IdentityService.get_public_key(identity_id, auto_provision=False) is None
    finally:
        config.TRUST_ROOT = original_root


def test_identity_service_corrupt_public_key(tmp_path):
    """Verify load public key exception raises for corrupted public_key.pem."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    try:
        identity_id = "corrupt_pub"
        id_dir = config.TRUST_ROOT / identity_id
        id_dir.mkdir(parents=True, exist_ok=True)

        with open(id_dir / "public_key.pem", "wb") as f:
            f.write(b"CORRUPTED_PUBLIC_KEY")

        with pytest.raises(ValueError):
            IdentityService.get_public_key(identity_id, auto_provision=False)
    finally:
        config.TRUST_ROOT = original_root
