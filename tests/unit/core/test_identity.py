import pytest
from pathlib import Path
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
            encryption_algorithm=serialization.NoEncryption()
        )
        bytes_b = key_1b.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        assert bytes_a == bytes_b
    finally:
        config.TRUST_ROOT = original_root
