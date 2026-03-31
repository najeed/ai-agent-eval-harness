import pytest
import os
from pathlib import Path
from eval_runner.verifier import TraceVerifier, FINGERPRINT_V1_SCHEMA

def test_fingerprint_schema_structure():
    """Verify FINGERPRINT_V1_SCHEMA has the required core fields."""
    assert "fingerprint_version" in FINGERPRINT_V1_SCHEMA
    assert "tool_dna" in FINGERPRINT_V1_SCHEMA
    assert isinstance(FINGERPRINT_V1_SCHEMA["tool_dna"], list)

def test_key_generation(tmp_path):
    """Test generating ED25519 key pair."""
    key_dir = tmp_path / "keys"
    TraceVerifier.generate_key_pair(str(key_dir))
    
    assert (key_dir / "private_key.pem").exists()
    assert (key_dir / "public_key.pem").exists()
    
    # Check if they are PEM formatted
    priv_content = (key_dir / "private_key.pem").read_text()
    pub_content = (key_dir / "public_key.pem").read_text()
    
    assert "-----BEGIN PRIVATE KEY-----" in priv_content
    assert "-----BEGIN PUBLIC KEY-----" in pub_content

def test_asymmetric_sign_verify(tmp_path):
    """Test signing and verifying data with ED25519."""
    key_dir = tmp_path / "keys"
    TraceVerifier.generate_key_pair(str(key_dir))
    
    priv_path = str(key_dir / "private_key.pem")
    pub_path = str(key_dir / "public_key.pem")
    
    data = b"Enterprise Trust Protocol Trace Data"
    signature = TraceVerifier.sign_asymmetric(data, priv_path)
    
    # 1. Success case
    assert TraceVerifier.verify_asymmetric(data, signature, pub_path) is True
    
    # 2. Tampered data
    assert TraceVerifier.verify_asymmetric(b"Tampered", signature, pub_path) is False
    
    # 3. Invalid signature
    assert TraceVerifier.verify_asymmetric(data, "a" * 64, pub_path) is False

def test_verify_with_wrong_key(tmp_path):
    """Test verification fails with the wrong public key."""
    key_dir_1 = tmp_path / "keys1"
    key_dir_2 = tmp_path / "keys2"
    TraceVerifier.generate_key_pair(str(key_dir_1))
    TraceVerifier.generate_key_pair(str(key_dir_2))
    
    data = b"data"
    sig = TraceVerifier.sign_asymmetric(data, str(key_dir_1 / "private_key.pem"))
    
    # Verification with key 2 should fail
    assert TraceVerifier.verify_asymmetric(data, sig, str(key_dir_2 / "public_key.pem")) is False
